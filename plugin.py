import sys
import ssl
import logging as log
import csv
import sqlite3
import re
import httpx
import difflib
import json
import os
from datetime import datetime
import pathlib
import asyncio
from contextlib import contextmanager
from galaxy.api.plugin import Plugin, create_and_run_plugin
from galaxy.api.consts import Platform, LocalGameState
from galaxy.api.types import Authentication, Game, LicenseInfo, LicenseType, LocalGame
from winreg import *

# Constants
STORE = 0
TITLE = 1
KEY = 2

dir_path = os.path.dirname(os.path.realpath(__file__))

class GFNPlugin(Plugin):
    def __init__(self, reader, writer, token):
        super().__init__(
            Platform.Test,  # choose platform from available list
            "0.8",  # version
            reader,
            writer,
            token
        )
        self.local_games = []
        self.matched_games_cache = []
        self.gfn_games = []
        self.gfn_ids = {}
        self.file_names = ["cache.json", "cache2.json", "cache3.json"]
        self._data = None
        self.json_loaded = False
        
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
    
    async def check_update_library(self):
        check_file = pathlib.Path(dir_path + '/last_update.txt')
        if check_file.exists():
            if self.check_date() == str(datetime.now().date()):
                log.debug("Loading Library")
                await self.load_library()
            else:
                log.debug("Update Library")
                await self.update_library()
        else:
            log.debug("Update Library")
            await self.update_library()
    
    def check_date(self):
        with open(dir_path + '/last_update.txt', 'r') as r:
            current_dateTime = r.read()     
        return str(current_dateTime)
                   
    def create_basic_files(self):
        with open(dir_path + '/last_update.txt', 'w') as f:
            f.write(str(datetime.now().date()))
                
        with open(dir_path + '/gfn_library.csv', 'w+'):
            pass
        
    async def load_library(self): 
        if os.stat(dir_path + '/gfn_library.csv').st_size == 0:
            asyncio.run(self.update_library())
        else:
            with open(dir_path + '/gfn_library.csv', 'r') as lib:
                reader = csv.reader(lib,delimiter=',')
                for row in reader:     
                    self.gfn_games.append(row[0])
                    self.gfn_ids[row[0]] = row[1]
    
    async def update_library(self):
        self.create_basic_files()
                
        await self.get_API("",self.file_names[0]) #Get all games from Geforce Now library
        await self.get_API("after:\"NzUw==\"",self.file_names[1])
        await self.get_API("after:\"MTUwMA==\"",self.file_names[2]) 
        
        self.create_library()
        
        await self.load_library()
        
    def create_library(self):
        i = 0
        while(i < len(self.file_names)):
            if not self.json_loaded:
            # load data from JSON file
                with open(dir_path + '/' + self.file_names[i], 'r') as f:
                    _data = json.load(f)
                    i = i + 1
                
                json_loaded = True
        
            # save data into gfn gfn_library file
            items = _data['data']['apps']['items']
            with open(dir_path + '/gfn_library.csv', 'a') as f:
                w = csv.writer(f, delimiter=',')
                for item in items:
                    name = item['title']
                    variants = item['variants']
                    for variant in variants:
                        store = variant['appStore']
                        id = variant['id']
                        
                        gg_id = self.gfn_convert(store, name)
                        
                        my_dict = {gg_id: 1, id : 2}
                        w.writerow(my_dict)
                                
        os.remove(dir_path + '/' + self.file_names[0])
        os.remove(dir_path + '/' + self.file_names[1])
        os.remove(dir_path + '/' + self.file_names[2])
    
    async def get_API(self, payload : str, cache_file : str):
        try:
            url = "https://api-prod.nvidia.com/gfngames/v1/gameList"
            headers = {
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
                        "Accept-Encoding": "gzip, deflate",
                        "Accept-Language": "en-US,en;q=0.9",
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36",
            }
 
            async with httpx.AsyncClient(http2=True, timeout=10, headers=headers) as client:
                _payload = f'{{apps(country:"US" language:"en_US" {payload}){{numberReturned,pageInfo{{endCursor,hasNextPage}},items{{title,sortName,variants{{appStore,publisherName,id}}}}}}}}\r\n'
                response = await client.post(url, data=_payload.encode('utf-8'))
                if response.status_code == 200:
                        json_data = response.json()
                        with open(dir_path + "/" + cache_file, "w",encoding="utf-8") as f:
                            json.dump(json_data, f)
                            
                elif response.status_code == 500:
                        await asyncio.sleep(5)
                        await self.get_API(payload, cache_file)
                else:
                        log.debug(
                            "Failure contacting GFN server, response code: {0}".format(
                                response.status_code
                            )
                        )
                        
        except Exception as ex:
            log.debug(ex)
        except httpx.TimeoutException as st:
            log.debug(st)
            await asyncio.sleep(10)
            await self.get_API(payload, cache_file)  # Try again
   
    async def get_games(self):
        try:
            await self.check_update_library()
        
            asyncio.create_task(self.get_local_games())
            
            with self.open_db() as cursor:
                sql = """
                    select distinct substr(gp.releaseKey,1,instr(gp.releaseKey,'_')-1) platform,
                    replace(substr(value,instr(value,':"')+2),'"}','') title, gp.releaseKey
                    from gamepieces gp
                    join gamepiecetypes gpt on gp.gamepiecetypeid = gpt.id
                        where gpt.type = 'title' and gp.releaseKey not like 'test_%' and gp.releaseKey not like 'gfn_%'
                """
                cursor.execute(sql)
                owned_games = list(cursor.fetchall())
            
            for game in owned_games:
                own = self.gfn_convert(game[STORE], game[TITLE])

                # Search for a match using the startswith method
                match = None
                for gfn_game in self.gfn_games:
                    if gfn_game.startswith(own):
                        match = gfn_game
                        break
                # If no match found, use difflib
                if not match:
                    close_matches = difflib.get_close_matches(own, self.gfn_games, n=1, cutoff=0.9)
                    if close_matches:
                        match = close_matches[0]

                if match:
                    game_id = 'gfn_' + str(self.gfn_ids[match])
                    self.matched_games_cache.append(Game(game_id, game[TITLE], None, LicenseInfo(LicenseType.SinglePurchase)))
                    local_game = LocalGame(game_id, LocalGameState.Installed)
                    self.local_games.append(local_game)


            log.debug('Matched games: {0}'.format(str(self.matched_games_cache)))
            return self.matched_games_cache
        except Exception as ex:
            log.debug(ex)
    
    @contextmanager
    def open_db(self):
		# Prepare the DB connection
        database_location = '{0}/GOG.com/Galaxy/storage/galaxy-2.0.db'.format(os.getenv('ProgramData'))
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
        a_key = r"GeForceNOW\Shell\Open\Command"
        a_reg = ConnectRegistry(None, HKEY_CLASSES_ROOT)
        a_key = OpenKey(a_reg, a_key)
        gfn_id = game_id.replace('gfn_', '')
        log.debug("Game id is {0}".format(gfn_id))
        gfn_app = '"' + QueryValue(a_key, None) + ' --url-route="#?cmsId=' + str(gfn_id) + '&launchSource=External""'
        log.debug("Launch command is {0}".format(gfn_app))

        os.system(gfn_app)
    
    async def get_local_games(self):
        await asyncio.sleep(3)
        log.debug('Local games: {0}'.format(self.local_games))
        return self.local_games

def main():
    create_and_run_plugin(GFNPlugin, sys.argv)

# run plugin event loop
if __name__ == "__main__":
    main()
