from collections import namedtuple
from operator import itemgetter
from blessings import Terminal

import numpy as np
from numpy.linalg import norm

GameStateBase = namedtuple('GameStateBase', ('field', 'rows', 'player'))
t = Terminal()


# noinspection PyTypeChecker
class GameState(GameStateBase):
    __slots__ = []
    player_symbols = {
        0: ' ',
        1: t.bold_red('X'),
        2: t.bold_blue('O'),
    }
    pre_field = ' 0 1 2 3 4 5 6'
    pre_line = '|'
    post_line = '|'
    divider = ' '
    post_field = '+-------------+'

    def __new__(cls, field=None, rows=None, player=1, num_rows=6, num_cols=7):
        if field is None:
            field = np.zeros((num_rows, num_cols), dtype=np.uint8)
            rows = [num_rows-1] * num_cols
        # noinspection PyArgumentList
        return GameStateBase.__new__(cls, field, rows, player)

    def __repr__(self):
        result = self.pre_field
        result += '\n' if self.pre_field else ''
        won = self.last_move_won()
        for y, row in enumerate(self.field.astype(int)):
            result += self.pre_line
            for x, val in enumerate(row):
                if x > 0:
                    result += self.divider
                result += self.player_symbols[val]
            result += self.post_line+'\n'
        result += self.post_field
        return result

    def put(self, col):
        field = self.field.copy()
        rows = self.rows[:]
        field[rows[col], col] = self.player
        rows[col] -= 1
        return GameState(field, rows, self.other_player)

    @property
    def other_player(self):
        return 2 if self.player == 1 else 1

    def check_rows(self, check, n=4):
        for i in range(check.shape[1] - n + 1):
            if np.any(np.all(check[:, i: i+n], 1)):
                return True
        return False

    @property
    def possible_moves(self):
        return tuple(i for i, row in enumerate(self.rows) if row >= 0)

    def last_move_won(self, n=4):
        check = self.field == self.other_player
        if check.sum() < 4:
            return None
        shape = check.shape

        for row in range(shape[0]):
            for col in range(shape[1]):
                for x_fact, y_fact in ((0, 1), (1, 0), (1, 1), (-1, 1)):
                    coords = [(row+i*y_fact, col+i*x_fact) for i in range(4)]
                    for coord in coords:
                        if coord[0] < 0 or coord[1] < 0:
                            break
                    else:
                        if x_fact == 1 and y_fact == 0:
                            pass
                        try:
                            values = check[tuple(zip(*coords))]
                        except IndexError:
                            continue
                        if np.all(values):
                            return coords

        return None

    def coords_score_for(self, row, col, player):
        result = 0
        for x_fact, y_fact in ((0, 1), (1, 0), (1, 1), (-1, 1)):
            for start in range(-3, 1):
                coords = [(row+i*y_fact, col+i*x_fact) for i in range(start, start+4)]
                for coord in coords:
                    if coord[0] < 0 or coord[1] < 0:
                        break
                else:
                    if x_fact == 1 and y_fact == 0:
                        pass
                    try:
                        values = self.field[tuple(zip(*coords))]
                    except IndexError:
                        continue
                    if np.sum(values == 0) == 2 and np.sum(values == player) == 2:
                        result += 1
        return result

    def get_best_move(self):
        reachable_states = {}
        for move in self.possible_moves:
            new_state = self.put(move)
            if new_state.last_move_won():
                # this moves makes us win, so do it!
                return move

            for next_move in new_state.possible_moves:
                new_new_state = new_state.put(next_move)
                if new_new_state.last_move_won():
                    # this move enables the opponent to win, so don't do it!
                    break
            else:
                reachable_states[move] = new_state

        good_for_us = {}
        bad_for_them = {}
        good_for_them = {}
        score_for_us_later = {}

        reachable_positions = [(self.rows[col], col) for col in reachable_states.keys()]
        for row, col in reachable_positions:
            score_we = self.coords_score_for(row, col, self.player)

            if score_we:
                good_for_us[col] = score_we

            score_them = self.coords_score_for(row, col, self.other_player)
            if score_them:
                bad_for_them[col] = score_them

            next_state = state.put(col)

            if row >= 0:
                score_them_above = next_state.coords_score_for(row-1, col, self.other_player)
                if score_them_above:
                    good_for_them[col] = score_them_above

            score_for_us_later[col] = sum((next_state.coords_score_for(next_state.rows[col], col, self.player)
                                           for col in next_state.possible_moves))

        # print('good for us', good_for_us)
        # print('bad for them', bad_for_them)
        # print('good for them', good_for_them)
        # print('score_for_us_later', score_for_us_later)

        final_score = {}
        for row, col in reachable_positions:
            final_score[col] = (good_for_us.get(col, 0) + bad_for_them.get(col, 0) - good_for_them.get(col, 0)*0.4)
        # print('final score', final_score)

        max_score = max(final_score.values())
        best_choices = [col for col, score in final_score.items() if score == max_score]

        deciding_score = {col: score_for_us_later.get(col, 0) for col in best_choices}
        max_score = max(deciding_score.values())
        best_choices = [col for col, score in deciding_score.items() if score == max_score]

        best_choices_scored = {}
        bottom_center = np.array((self.field.shape[0]-1, (self.field.shape[1]-1)/2))
        for col in best_choices:
            best_choices_scored[col] = norm((bottom_center-np.array((self.rows[col], col)))*np.array((0.9, 1)))

        return min(best_choices_scored.items(), key=itemgetter(1))[0]


computer_players = []

for player in (1, 2):
    print('Player %s is a computer? (y/n)' % player)
    data = ''
    while data not in ('y', 'n'):
        data = input('>>> ')
    if data == 'y':
        computer_players.append(player)
    print()

computer_wait = False
if computer_players:
    print('Wait after computer moves? (y/N)')
    data = None
    while data not in ('y', 'n', 'N', ''):
        data = input('>>> ')
    computer_wait = (data == 'y')
    print()

state = GameState()
player = state.player
while True:
    print(state)
    print()

    if state.last_move_won():
        print('Player %d (%s) won!' % (player, 'Computer' if player in computer_players else 'Human'))
        break

    if not state.possible_moves:
        print('Noone won!')
        break

    player = state.player

    print('Player %d (%s, %s) moves:' % (player, ' XO'[player], 'computer' if player in computer_players else 'human'))
    if player in computer_players:
        if computer_wait:
            input('Enter to continue:\n>>> ')
        state = state.put(state.get_best_move())
    else:
        data = ''
        possible = [str(s) for s in state.possible_moves]
        while data not in possible:
            data = input('Select column (%s) to continue:\n>>> ' % ', '.join(possible))
        state = state.put(int(data))

