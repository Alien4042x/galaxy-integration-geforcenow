import sys
import ssl
import logging as log
import csv
import sqlite3
import re
import requests
import os
import subprocess
from datetime import datetime
import pathlib
import asyncio
from contextlib import contextmanager
from galaxy.api.plugin import Plugin, create_and_run_plugin
from galaxy.api.consts import Platform, LocalGameState
from galaxy.api.types import Authentication, Game, LicenseInfo, LicenseType, LocalGame

# Constants
STORE = 0
TITLE = 1
KEY = 2

dir_path = os.path.dirname(os.path.realpath(__file__))

class GFNPlugin(Plugin):
    def __init__(self, reader, writer, token):
        super().__init__(
            Platform.Test,  # choose platform from available list
            "0.3",  # version
            reader,
            writer,
            token
        )
        ssl._create_default_https_context = ssl._create_unverified_context

    # implement methods
    gfn_games = []
    gfn_ids = {}

    def gfn_convert(self,_store: str,_title: str):
        _store = _store.lower()
        if _store == 'ubisoft connect':
            _store = 'uplay'

        elif _store == 'ea_app':# In future will need probably edit
            _store = 'origin'

        _title = _title.replace('&', 'and')
        _title = re.sub(r'[\W_]+', '_', _title.lower())
        if _title[-1] == '_':
            _title = _title.rstrip(_title[-1])

        return _store + '_' + _title

    async def name_fix(self, _original: str):
        global gfn_mappings

        translated = _original

        if _original in self.gfn_mappings:
            translated = self.gfn_mappings[_original]
            log.debug('Translating {0} to {1}', _original, translated)

        return translated
    
    def check_update_library(self):
        check_file = pathlib.Path(dir_path + '/last_update.txt')
        if (check_file.exists()):
            self.load_library()
            log.debug("Loading Library")
        else:
            log.debug("Update Library")
            self.last_update()
            
            self.get_API("") #Get all games from Geforce Now library
            asyncio.sleep(5)
            self.get_API("after:\"NzUw\"")
            asyncio.sleep(5)
            self.get_API("after:\"MTUwMA==\"")
            asyncio.sleep(15)
            self.load_library()
            
    def last_update(self):
        with open(dir_path + '/last_update.txt', 'w+') as w:
            current_dateTime = datetime.now()
            w.write(str(current_dateTime.date()))
            
        with open(dir_path + '/gfn_library.csv', 'w+'):
            pass
        
    def load_library(self):
        with open(dir_path + '/gfn_library.csv', mode='r') as infile:
            reader = csv.reader(infile,delimiter=',')
            for row in reader:     
                self.gfn_games.append(row[0])
                self.gfn_ids[row[0]] = row[1]
        
    def get_API(self, _payload : str):
        try:
            url = "https://api-prod.nvidia.com/gfngames/v1/gameList"
            headers = {'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en;q=0.9',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36'}
            _payload = f'{{apps(country:"US" language:"en_US" {_payload}){{numberReturned,pageInfo{{endCursor,hasNextPage}},items{{title,sortName,variants{{appStore,publisherName,id}}}}}}}}\r\n'
            response = requests.post(url, headers=headers, data=_payload, timeout=5)
            
            if response.status_code == 200:
                json_data = response.json()
                
                items = json_data['data']['apps']['items']
                for item in items:
                    name = item['title']
                    variants = item['variants']
                    for variant in variants:
                        store = variant['appStore']
                        id = variant['id']

                        gg_id = self.gfn_convert(store, name)
                        
                        with open(dir_path + '/gfn_library.csv', 'a') as f:
                            w = csv.writer(f, delimiter=',')
                            my_dict = {gg_id: 1, id : 2}
                            w.writerow(my_dict)
                            
            elif response.status_code == 500:#Try again
                self.get_API(_payload)
            else:
                log.error("Failure contacting GFN server, response code: {0}".format(response.status_code))

        except requests.Timeout as st:
            log.debug(st)
            asyncio.sleep(5)
            self.get_API(_payload)#Try again

    def _gfn_mapping(self):
        global local_games
        global gfn_mappings

        self.gfn_mappings = {}
        mappings_file = pathlib.Path(__file__).resolve().parent.joinpath('gfn_mappings.csv')
        if mappings_file.is_file():
            with open(mappings_file, mode='r') as infile:
                reader = csv.reader(infile)
                self.gfn_mappings = {rows[0]: rows[1] for rows in reader}
                log.debug('Mappings: {0}'.format(str(self.gfn_mappings)))
        else:
            log.debug('Could not find mappings file [{0}]'.format(str(mappings_file)))
    
    async def get_games(self):
        #self._gfn_mapping()
        
        self.check_update_library()

        with self.open_db() as cursor:
            sql = """
                select distinct substr(gp.releaseKey,1,instr(gp.releaseKey,'_')-1) platform,
                replace(substr(value,instr(value,':"')+2),'"}','') title, gp.releaseKey
                from gamepieces gp
                join gamepiecetypes gpt on gp.gamepiecetypeid = gpt.id
                    where gpt.type = 'originalTitle' and gp.releaseKey not like 'test_%' and gp.releaseKey not like 'gfn_%'
            """
            cursor.execute(sql)
            owned_games = list(cursor.fetchall())

        matched_games = []
        local_games = []
        #log.debug("GFN games: {0}".format(gfn_games))
        #log.debug("GFN ids: {0}".format(gfn_ids))

        for game in owned_games:
            own = self.gfn_convert(game[STORE], game[TITLE])
            for gfn in self.gfn_games:
                if(gfn == own):
                    game_id = ''
                    if gfn in self.gfn_games:
                        game_id = 'gfn_' + str(self.gfn_ids[gfn])
                    #else:
                        #log.debug("Not found {0}: {1} [{2}]".format(game[STORE], game[TITLE], gfn))

                    if game_id != '':
                        #log.debug("Found {0}: {1} [{2}] [{3}]".format(game[STORE], game[TITLE], gfn, game_id))
                        matched_games.append(Game(game_id, game[TITLE], None, LicenseInfo(LicenseType.SinglePurchase)))
                        local_game = LocalGame(game_id, LocalGameState.Installed)
                        self.local_games.append(local_game)

        log.debug('Matched games: {0}'.format(str(matched_games)))
        return matched_games

    @contextmanager
    def open_db(self):
    # Prepare the DB connection
        database_location = '/Users/Shared/GOG.com/Galaxy/storage/galaxy-2.0.db'
        _connection = sqlite3.connect(database_location)
        _cursor = _connection.cursor()

        _exception = None
        try:
            yield _cursor
        except Exception as e:
            _exception = e

		# Close the DB connection
        _cursor.close()
        _connection.close()

		# Re-raise the unhandled exception if needed
        if _exception:
            raise _exception
    # required
    async def authenticate(self, stored_credentials=None):
        return Authentication('anonymous', 'Anonymous')

    async def get_owned_games(self):
        return await self.get_games()

    async def launch_game(self, game_id):
        gfn_id = game_id.replace('gfn_', '')
        get_file = dir_path + '/gfn_play/GFC_Runner.gfnpc'
        log.debug("File_Path: "+ get_file)
        with open(get_file, 'w') as f:
            f.write(str('{'+
            '"url-route"' ':' '"#?cmsId={id}&launchSource=External"'.format(id=gfn_id)+
            '}')
        )
        #log.debug("Launch command is {0}".format(gfn_app))

        subprocess.Popen(['open', get_file])

    local_games = []
    gfn_mappings = {}
    # required
    async def get_local_games(self):
        global local_games
        log.debug('Local games: {0}'.format(self.local_games))
        return self.local_games


def main():
    create_and_run_plugin(GFNPlugin, sys.argv)

# run plugin event loop
if __name__ == "__main__":
    main()
