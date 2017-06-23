import json
import os
import pickle
import time
import traceback
from datetime import datetime, timedelta
from queue import Queue
from threading import Thread

import numpy as np
import tweepy

from m4connect import GameState

GameState.pre_field = ''
GameState.pre_line = ''
GameState.post_line = ''
GameState.divider = ''
GameState.post_field = ''
GameState.player_symbols = {
    0: '⚪',
    1: '🔵',
    2: '🔴',
}
player_symbols_inverted = {v: n for n, v in GameState.player_symbols.items()}


def save_state(state, filename):
    pickle.dump(state, open('states/gamestate_'+filename+'.pickle', 'wb'))


def load_state(filename):
    return pickle.load(open('states/gamestate_'+filename+'.pickle', 'rb'))


def delete_state(filename):
    return os.remove('states/gamestate_' + filename + '.pickle')


# noinspection PyTypeChecker
def parse_state(message, parent=None):
    state = GameState()
    field = np.array([player_symbols_inverted[char] for char in message if char in player_symbols_inverted])
    if field.size != state.field.size:
        return 'Your field has the wrong size!'
    field = field.astype(state.field.dtype).reshape(state.field.shape)
    first_move = False
    if parent is None:
        if not np.any(field != 0):
            return state
        first_move = True
        parent = state
    possible_states = []
    for move in parent.possible_moves:
        possible_states.append(parent.put(move))
    if first_move:
        parent = GameState(player=2)
        for move in parent.possible_moves:
            possible_states.append(parent.put(move))
    for possible_state in possible_states:
        if np.all(possible_state.field == field):
            return possible_state
    if first_move:
        return 'That is not a valid first move.'
    return 'That is not a valid move.'


class StreamListener(tweepy.StreamListener):
    def __init__(self, dispatcher, screen_name):
        super(StreamListener, self).__init__(None)
        self.screen_name = screen_name
        self.dispatcher = dispatcher
        print('[StreamListener] connected!')

    def on_status(self, tweet):
        print('[StreamListener] ran on_status')

    def on_error(self, status_code):
        print('[StreamListener] Error: ' + repr(status_code))
        return False

    def on_data(self, rawdata):
        data = json.loads(rawdata)

        if data.get('in_reply_to_screen_name', '') != self.screen_name:
            return

        user_name = data.get('user', {}).get('name', '')
        screen_name = data.get('user', {}).get('screen_name', '')
        status_id = data.get('id_str', None)
        print('[StreamListener] incoming tweet from %s (@%s):' % (user_name, screen_name))

        text = data.get('text', '')

        print('[StreamListener] '+repr(text))
        parent = None
        filename = None
        in_reply_to_status_id = data.get('in_reply_to_status_id_str', None)
        if in_reply_to_status_id is not None:
            filename = screen_name+'_'+in_reply_to_status_id
            print('[StreamListener] This is a reply, so let\'s load the parent!')
            try:
                parent = load_state(filename)
            except FileNotFoundError:
                print('[StreamListener] File not found. ignoring.')
                return
            except:
                print('[StreamListener] Something else happened. ignoring.')
                traceback.print_exc()
                return

        not_one_symbol = False
        for char in player_symbols_inverted:
            if char in text:
                break
        else:
            not_one_symbol = True

        tweet_prefix = '@'+screen_name+'\n'

        if parent is None and not_one_symbol and 'STARTGAME' in text:
            state = GameState()
        else:
            state = parse_state(text, parent=parent)

        if isinstance(state, str):
            print('[StreamListener] invalid: '+state)
            if not_one_symbol or parent is None:
                print('[StreamListener] no game symbols or initial tweet without STARTGAME. ignoring.')
                return

            self.dispatcher.tweet(text=tweet_prefix+state, in_reply_to=status_id)
            return

        print('[StreamListener] valid state!')
        if filename is not None:
            delete_state(filename)

        if state.last_move_won():
            print('[StreamListener] Oponnent won! Congratulations!')
            self.dispatcher.tweet(text=tweet_prefix+'You win! 👏 🌈 Congratulations!', in_reply_to=status_id)
            return

        print('[StreamListener] determining our next move...')
        try:
            new_state = state.put(state.get_best_move())
            won = new_state.last_move_won()

            reply = tweet_prefix+repr(new_state)+'\n'

            # noinspection PyTypeChecker
            if not np.any(new_state.field == new_state.player):
                reply += 'The game is on! Your Emoji is: %s' % new_state.player_symbols[new_state.player]
            if won:
                print('[StreamListener] ...and we won! Yeah!')
                reply += 'I win! 😎'

            self.dispatcher.tweet(text=reply, in_reply_to=status_id, state=(None if won else new_state),
                                  filename_prefix=screen_name+'_')

        except:
            print('[StreamListener] Oh no, something went wrong!')
            traceback.print_exc()
            return

        print('[StreamListener] done!')


class TweetDispatcher:
    time_between_tweets = timedelta(seconds=42)

    def __init__(self, api):
        self.api = api
        self.last_tweet = datetime.now() - timedelta(seconds=15)
        self.tweet_queue = Queue()

    def run(self):
        while True:
            wait_seconds = (self.time_between_tweets-(datetime.now()-self.last_tweet)).total_seconds()
            if wait_seconds > 0:
                print('[TweetDispatcher] wait for %ds to satisfy the rate limit…' % wait_seconds)
                time.sleep(wait_seconds)
            else:
                time.sleep(1)

            print('[TweetDispatcher] ready to tweet again!')

            try:
                text, in_reply_to, state, filename_prefix = self.tweet_queue.get()
                print('[TweetDispatcher] tweeting:\n'+text)
                kwargs = {}
                if in_reply_to is not None:
                    kwargs['in_reply_to_status_id'] = in_reply_to
                self.last_tweet = datetime.now()
                status = self.api.update_status(text, **kwargs)

                if state is not None:
                    print('[TweetDispatcher] saving state: '+filename_prefix+status.id_str)
                    save_state(state, filename_prefix+status.id_str)
            except:
                print('[TweetDispatcher] Oh no, something went wrong!')
                traceback.print_exc()

    def tweet(self, text, in_reply_to=None, state=None, filename_prefix=''):
        print('[TweetDispatcher] Queueing tweet:\n%s' % text)
        self.tweet_queue.put((text, in_reply_to, state, filename_prefix))


def start_stream(auth, dispatcher, screen_name):
    lastconnect = 0
    wait = 60
    while True:
        if lastconnect + 60 >= time.time():
            print('[StreamListener] waiting to reconnect…')
            time.sleep(wait)
            wait = wait * 2
        else:
            wait = 90
        lastconnect = time.time()
        tweepy.Stream(auth=auth, listener=StreamListener(dispatcher, screen_name)).filter(track=[screen_name])
        print('[StreamListener] disconnected!')


try:
    auth_data = json.load(open('twitterauth.data', 'r'))
except FileNotFoundError:
    print('I need authorisation!')
    print('Please register an app!')
    # noinspection PyDictCreation
    auth_data = {}
    auth_data['consumer_key'] = input('consumer_key >>> ').strip()
    auth_data['consumer_secret'] = input('consumer_secret >>> ').strip()
    auth = tweepy.OAuthHandler(auth_data['consumer_key'], auth_data['consumer_secret'])
    print('You can now authenticate here:', auth.get_authorization_url(access_type='read-write'))
    verifier = input('verifier >>> ').strip()
    auth.get_access_token(verifier)
    auth_data['access_token'] = auth.access_token
    auth_data['access_token_secret'] = auth.access_token_secret
    print('Done! Thanks! Saved to twitterauth.data.')
    twitter_api = tweepy.API(auth)
    auth_data['screen_name'] = twitter_api.me().screen_name
    json.dump(auth_data, open('twitterauth.data', 'w'))
    print('Done! Logged in as @%s! Login data saved to twitterauth.data' % auth_data['screen_name'])
else:
    auth = tweepy.OAuthHandler(auth_data['consumer_key'], auth_data['consumer_secret'])
    auth.set_access_token(auth_data['access_token'], auth_data['access_token_secret'])
    twitter_api = tweepy.API(auth)

tweet_dispatcher = TweetDispatcher(twitter_api)
thread = Thread(target=tweet_dispatcher.run)
thread.start()

thread = Thread(target=start_stream, args=(auth, tweet_dispatcher, auth_data['screen_name']))
thread.start()
