#!/usr/bin/env python3

import argparse
import datetime
import git
import glob
import multiprocessing.pool
import os
import random
import shutil
import subprocess
import sys
import threading
import typing

import edq.util.dirent
import edq.util.json

import stats

RUN_DIRNAME = '140_tournament'
RESULTS_FILENAME = 'results.json'
MATCHES_DIRNAME = 'matches'

PACMAN_REPO_URL = 'https://github.com/edulinq/pacai'
PACMAN_TAG = 'v2.1.0'

TEAM_SOURCE_FILENAME = 'capture.py'
TEAM_NAME_FILENAME = 'capture-team.txt'
TEAM_PREFIX = 'team'
CAPTURE_TEAM_FUNC = 'create_team'
CODE_DIRNAME = 'code'
STUDENT_DIRNAME = os.path.join('pacai', 'student')

# Special teams that we do not want to run in the tournament.
IGNORE_SPECIAL_TEAMS = {'_crash', '_start_timeout', '_timeout', '_cheating'}

# Student teams that we do not want to run in the tournament.
DISQUALIFY_TEAMS = {}

# These are the main things to be changes.
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
BASE_OUT_DIR = os.path.join(BASE_DIR, 'out')
SPECIAL_TEAMS_DIR = os.path.join(BASE_DIR, 'special_teams')
TEAMS_DIR = os.path.join(BASE_DIR, '_teams')
BASE_SUBMISSION_DIR = os.path.join(BASE_DIR, '_submissions')


SOLUTION_DIRS = [
    os.path.join(BASE_DIR, '..' , 'p1', 'test-submissions','solution'),
    os.path.join(BASE_DIR, '..' , 'p2', 'test-submissions','solution'),
    os.path.join(BASE_DIR, '..' , 'p3', 'test-submissions','solution'),
]

AGENT_ACTION_TIMEOUT = '3'
AGENT_START_TIMEOUT = '15'
AGENT_END_TIMEOUT = '6'
MAX_TURNS = '1200'
SKIP_FRAMES = 3
FPS = 20

DEFAULT_BOARD_GAMES = 5
RANDOM_BOARD_GAMES = 6

# Run a single game of capture.
def run_game(code_dir, save_path, log_path, game_stats_path, board,
        red_file_basename, blue_file_basename, red_team_name, blue_team_name,
        output_webp, webp_path) -> typing.Union[None, stats.GameStats]:

    args = [
        'python3',
        '-m', 'pacai.capture',
        '--red-team', red_file_basename,
        '--blue-team', blue_file_basename,
        '--save-path', save_path,
        '--board', board,
        '--ui','null',
        '--isolation', 'process',
        '--agent-start-timeout', AGENT_START_TIMEOUT,
        '--agent-end-timeout', AGENT_END_TIMEOUT,
        '--agent-action-timeout', AGENT_ACTION_TIMEOUT,
        '--max-turns', MAX_TURNS
    ]

    if (output_webp):
        args += [
            '--animation-skip-frames', str(SKIP_FRAMES),
            '--animation-fps', str(FPS),
            '--animation-optimize',
            '--animation-path', webp_path
        ]

    game_stats = None

    result = subprocess.run(
        args,
        capture_output = True,
        shell = False,
        cwd = code_dir,
        check = True,
        text = True
    )

    game_result = edq.util.json.load_path(save_path)
    edq.util.dirent.write_file(log_path, result.stdout)
    edq.util.dirent.write_file(log_path, result.stderr)


    if (result.returncode != 0):
        return None

    game_stats = stats.GameStats(
        red_team_name,
        blue_team_name,
        board,
        game_result
    )

    edq.util.json.dump_path(game_stats.to_dict(), game_stats_path, indent = 4)
    return game_stats

def get_pacman_template_repo():
    path = edq.util.dirent.get_temp_path(prefix = 'tournament-', suffix = '-pacman')

    repo = git.Repo.clone_from(PACMAN_REPO_URL, path)
    repo.git.checkout(PACMAN_TAG)

    return path

# Returns the names to invoke each team with: (red, blue).
def prepare_code_directory(out_dir, pacman_dir, red_name, red_dir, blue_name, blue_dir):
    edq.util.dirent.remove(out_dir)

    # Copy over all the template code.
    edq.util.dirent.copy(pacman_dir, out_dir)

    # Copy over all the previous project solutions.
    for solution_dir in SOLUTION_DIRS:
        for path in glob.glob(os.path.join(solution_dir, '*.py')):
            edq.util.dirent.copy_contents(path, os.path.join(out_dir, STUDENT_DIRNAME))

    # Copy in the teams' submissions.
    names = []
    for (name, code_dir) in [(red_name, red_dir), (blue_name, blue_dir)]:
        out_name = f'{TEAM_PREFIX}_{name}'
        names.append('pacai.student.' + out_name + f'.{CAPTURE_TEAM_FUNC}')

        code_path = os.path.join(code_dir, TEAM_SOURCE_FILENAME)
        dest_path = os.path.join(out_dir, STUDENT_DIRNAME, f'{out_name}.py')

        edq.util.dirent.copy(code_path, dest_path)

    return tuple(names)

# Take in a team's dir and pass back the team's name if the team is valid.
# Return None if the team is invalid.
def validate_team(path):
    for filename in [TEAM_SOURCE_FILENAME, TEAM_NAME_FILENAME]:
        if (not os.path.isfile(os.path.join(path, filename))):
            return None

    name = None
    with open(os.path.join(path, TEAM_NAME_FILENAME), 'r') as file:
        for line in file:
            name = line.strip()

    return name

def collect_teams(dir):
    teams = []

    for dirent in os.listdir(dir):
        team_path = os.path.join(dir, dirent)
        if (not os.path.isdir(team_path)):
            continue

        name = validate_team(team_path)
        if (name is None):
            continue

        if ((name in IGNORE_SPECIAL_TEAMS) or (name in DISQUALIFY_TEAMS) ):
            continue

        teams.append((name, team_path))

    return teams

def run_match(pacman_dir, tournament_id, run_basedir, matches_dir, red, blue, output_webp) -> stats.MatchStats:
    thread_id = threading.get_ident()

    red_name, red_path = red
    blue_name, blue_path = blue

    output_basename = f'{tournament_id}_{red_name}_vs_{blue_name}'
    output_dir = os.path.join(matches_dir, output_basename)

    match_name = f'{tournament_id}_{red_name}_vs_{blue_name}'
    match_stats_path = os.path.join(output_dir, f'{match_name}_matchstats.json')

    # If the match stats file exists, then don't bother running the match.
    if (edq.util.dirent.exists(match_stats_path)):
        print(f'Skipping Match -- {red_name} vs {blue_name}')
        return edq.util.json.load_path(match_stats_path)

    print(f'Running Match -- {red_name} vs {blue_name}', flush = True)

    run_dir = os.path.join(run_basedir, f'worker_{thread_id}')
    edq.util.dirent.mkdir(run_dir)

    code_dir = os.path.join(run_dir, CODE_DIRNAME)
    red_file_basename, blue_file_basename = prepare_code_directory(code_dir, pacman_dir, red_name, red_path, blue_name, blue_path)

    edq.util.dirent.remove(output_dir)
    edq.util.dirent.mkdir(output_dir)

    boards = ['capture-default.board'] * DEFAULT_BOARD_GAMES

    for i in range(RANDOM_BOARD_GAMES):
        boards.append(f'random-{random.randint(0, 2 ** 32)}')

    match_stats = stats.MatchStats(red_name, blue_name)
    for i in range(len(boards)):
        game_id = f'{i:03d}'
        replay_path = os.path.join(output_dir, f'{match_name}_{game_id}.replay')
        webp_path = os.path.join(output_dir, f'{match_name}_{game_id}.webp')
        log_path = os.path.join(output_dir, f'{match_name}_{game_id}.log')
        game_stats_path = os.path.join(output_dir, f'{match_name}_{game_id}.json')

        game_stats = run_game(code_dir, replay_path, log_path, game_stats_path, boards[i],
                red_file_basename, blue_file_basename, red_name, blue_name,
                output_webp, webp_path)

        # If the game crashed in an unconventional way
        # (with the capture main() ultimately throwing and exception),
        # Then don't add this game to the match stats.
        if (game_stats is not None):
            match_stats.add_game(game_stats)

    # Write out the match stats.
    edq.util.json.dump_path(match_stats.to_dict(), match_stats_path, indent = 4)

    # Make an archived copy of the output directory.
    initial_archive_path = shutil.make_archive(
            os.path.join(matches_dir, output_basename), format = 'zip',
            root_dir = matches_dir, base_dir = output_basename)

    edq.util.dirent.remove(os.path.join(output_dir, os.path.basename(initial_archive_path)))
    shutil.move(initial_archive_path, output_dir)

    # Cleanup
    edq.util.dirent.remove(run_dir)

    print(f'Finished Match -- {red_name} vs {blue_name}', flush = True)

    return match_stats

def run_matches(run_basedir, teams, tournament_id, output_webp):
    matches_dir = os.path.join(run_basedir, MATCHES_DIRNAME)
    edq.util.dirent.mkdir(matches_dir)

    print(f'Running tournament with {len(teams)} teams in {run_basedir}.')

    random.shuffle(teams)

    # Fetch a fresh copy of the pacman code.
    pacman_dir = get_pacman_template_repo()

    with multiprocessing.pool.ThreadPool() as pool:
        jobs = []
        for red in teams:
            for blue in teams:
                if (red == blue):
                    continue

                jobs.append(pool.apply_async(run_match, (pacman_dir, tournament_id, run_basedir, matches_dir, red, blue, output_webp)))

        results = []
        for job in jobs:
            job.wait()
            results.append(job.get().to_dict())

    # Cleanup.
    edq.util.dirent.remove(pacman_dir)

    return results

def main(tournament_id, output_webp):
    # [(name, path), ...]
    teams = []
    teams += collect_teams(SPECIAL_TEAMS_DIR)
    teams += collect_teams(TEAMS_DIR)

    run_basedir = os.path.join(BASE_OUT_DIR, RUN_DIRNAME, tournament_id)
    edq.util.dirent.mkdir(run_basedir)

    results_path = os.path.join(run_basedir, RESULTS_FILENAME)

    match_results = run_matches(run_basedir, teams, tournament_id, output_webp)

    # {team: [wins, ties, losses, team], ...}
    records = {}

    for match_result in match_results:
        for team in ['red', 'blue']:
            name = match_result[team]['name']

            if (name not in records):
                records[name] = [0, 0, 0, name]

            records[name][0] += match_result[team]['wins']
            records[name][1] += match_result[team]['ties']
            records[name][2] += match_result[team]['losses']

    records = sorted(records.values(), reverse = True)
    records = [{'name': record[3], 'wins': record[0], 'ties': record[1], 'losses': record[2]} for record in records]

    match_results.sort(key = lambda match: match['red']['name'] + '|||' + match['blue']['name'])

    results = {
        'records': records,
        'matches': match_results,
    };

    edq.util.json.dump_path(results, results_path, indent = 4)

def _load_args(args):
    datestamp = f'{datetime.datetime.now():%Y%m%d}'
    parser = argparse.ArgumentParser(description = 'Run a single tournament on the local machine.')

    parser.add_argument('--id',
            dest = 'id', action = 'store', default = datestamp,
            help = f'The identifier for this tournament. Default to the date {datestamp}.'
    )

    parser.add_argument('--webp',
            dest = 'webp', action = 'store_true', default = False,
            help = 'Generate the webps of each game (usually takes longer to run).'
    )

    args = parser.parse_args()

    return [args.id, args.webp]

if __name__ == '__main__':
    main(*_load_args(sys.argv))
