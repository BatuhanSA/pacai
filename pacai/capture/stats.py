import edq.util.json
import edq.util.serial

class GameStats(edq.util.serial.DictConverter):
    def __init__(self, red_team_name, blue_team_name, board, game_result):
        self.game_result = game_result

        self.board = board
        self.score = None
        self.time = 0
        self.is_game_timeout = False

        self.red_name = red_team_name
        self.red_time = 0
        self.red_timeout = False
        self.red_crash = False

        self.blue_name = blue_team_name
        self.blue_time = 0
        self.blue_timeout = False
        self.blue_crash = False

        # If capture didn't crash unconventionally
        if (game_result is not None):
            self._collect_stats()

    def get_stats(self, team):
        if (team != 'red' and team != 'blue'):
            raise Exception("Unknown team: '%s'." % (team))

        if (team == 'red'):
            return (self.red_crash, self.red_time, self.red_timeout)

        return (self.blue_crash, self.blue_time, self.blue_timeout)

    def _build_stats(self):
        stats = {
            'board': self.board,
            'score': self.score,
            'time': self.time,
            'is_game_timeout': self.is_game_timeout,
            'red': {
                'name': self.red_name,
                'win': False,
                'tie': False,
                'loss': False,
                'time': self.red_time,
                'timeouts': self.red_timeout,
                'crash': self.red_crash,
            },
            'blue': {
                'name': self.blue_name,
                'win': False,
                'tie': False,
                'loss': False,
                'time': self.blue_time,
                'timeouts': self.blue_timeout,
                'crash': self.blue_crash,
            },
        }

        if (self.game_result is not None):
            for agent_index in self.game_result["crash_agent_indexes"]:
                if (agent_index % 2 == 0):
                    stats['red']['loss'] = True
                    stats['blue']['win'] = True
                    stats['red']['crash'] = True
                else:
                    stats['red']['win'] = True
                    stats['blue']['loss'] = True
                    stats['blue']['crash'] = True
                return stats

            for agent_index in self.game_result["timeout_agent_indexes"]:
                if (agent_index % 2 == 0):
                    stats['red']['loss'] = True
                    stats['blue']['win'] = True
                    stats['red']['timeouts'] = True
                else:
                    stats['red']['win'] = True
                    stats['blue']['loss'] = True
                    stats['blue']['timeouts'] = True
                return stats

            for agent_index in self.game_result["winning_agent_indexes"]:
                if (agent_index % 2 == 0):
                    stats['red']['win'] = True
                    stats['blue']['loss'] = True
                else:
                    stats['red']['loss'] = True
                    stats['blue']['win'] = True
                return stats

            # If the game timed out
            if (self.game_result["score"] < 0):
                stats['red']['win'] = True
                stats['blue']['loss'] = True
            elif (self.game_result["score"] > 0):
                stats['red']['loss'] = True
                stats['blue']['win'] = True
            else:
                stats['red']['tie']  = True
                stats['blue']['tie'] = True

        return stats

    def to_dict(self):
        return self._build_stats()

    def _collect_stats(self):
        self.score = self.game_result["score"]
        self.time = ((self.game_result["end_time"] - self.game_result["start_time"]) / 1000)
        self.is_game_timeout = self.game_result["game_timeout"]

        # Timing and crash info.
        for agent_action_record in self.game_result["history"]:
            if (agent_action_record["agent_index"] % 2 == 0):
                self.red_time += (agent_action_record["duration"] / 1000)
            else:
                self.blue_time += (agent_action_record["duration"] / 1000)

# A match is a series of games.
class MatchStats(edq.util.serial.DictConverter):
    def __init__(self, red_name, blue_name):
        self._games_stats = []

        self.red_name = red_name
        self.blue_name = blue_name

    def add_game(self, game_stats):
        self._games_stats.append(game_stats)

    def to_dict(self):
        return self._accumulate()

    def __str__(self):
        return edq.util.json.dumps(self.to_dict(), indent = 4)

    def _accumulate(self):
        stats = {
            'boards': [],
            'scores': [],
            'times': [],
            'full_game_timeouts' : [],
            'red': {
                'name': self.red_name,
                'wins': 0,
                'ties': 0,
                'losses': 0,
                'times': [],
                'crashes': 0,
                'timeouts': 0,
            },
            'blue': {
                'name': self.blue_name,
                'wins': 0,
                'ties': 0,
                'losses': 0,
                'times': [],
                'crashes': 0,
                'timeouts': 0,
            },
        }

        for game_stats in self._games_stats:
            stats['boards'].append(game_stats.board)
            stats['scores'].append(game_stats.score)
            stats['times'].append(game_stats.time)
            stats['full_game_timeouts'].append(game_stats.is_game_timeout)

            for team in ['red', 'blue']:
                crash, time, timeout = game_stats.get_stats(team)

                stats[team]['crashes'] += int(crash)
                stats[team]['times'].append(time)
                stats[team]['timeouts'] += int(timeout)

            game_stats = game_stats.to_dict()
            if (game_stats['red']['crash'] or game_stats['red']['timeouts']):
                stats['red']['losses'] += 1
                stats['blue']['wins'] += 1
            elif (game_stats['blue']['crash'] or game_stats['blue']['timeouts']):
                stats['blue']['losses'] += 1
                stats['red']['wins'] += 1
            elif (game_stats['red']['win'] and game_stats['blue']['loss']):
                stats['red']['wins'] += 1
                stats['blue']['losses'] += 1
            elif (game_stats['blue']['win'] and game_stats['red']['loss']):
                stats['blue']['wins'] += 1
                stats['red']['losses'] += 1
            elif (game_stats['is_game_timeout']):
                if (game_stats['score'] < 0):
                    stats['red']['wins'] += 0.5
                    stats['blue']['losses'] += 0.5
                elif(game_stats['score'] > 0):
                    stats['red']['losses'] += 0.5
                    stats['blue']['wins'] += 0.5
                else:
                    stats['red']['ties'] += 1
                    stats['blue']['ties'] += 1

        return stats
