import sys
import json
import ssl
import logging as log
import csv
from pathlib import Path
import sqlite3
import re
import http.client
import os
import subprocess
import asyncio
from contextlib import contextmanager
from galaxy.api.plugin import Plugin, create_and_run_plugin
from galaxy.api.consts import Platform, LocalGameState
from galaxy.api.types import Authentication, Game, LicenseInfo, LicenseType, LocalGame

PLATFORM = 0
TITLE = 1
KEY = 2

class PluginExample(Plugin):
    def __init__(self, reader, writer, token):
        super().__init__(
            Platform.Test,  # choose platform from available list
            "0.1",  # version
            reader,
            writer,
            token
        )
        ssl._create_default_https_context = ssl._create_unverified_context

    # implement methods
    gfn_games = []
    gfn_steam = []
    gfn_ids = {}

    async def gfn_convert(self,_store: str,_title: str):
        _store = _store.lower()
        if _store == 'ubisoft connect':
            _store = 'uplay'
        elif _store == 'ea_app':# In future will need probably edit
            _store = 'origin'


        _title = re.sub(r'[\W_]+', '', _title.lower())
        #_title = _title.replace(" ", "").lower()

        return _store + '_' + _title

    async def name_fix(self, _original: str):
        global gfn_mappings

        translated = _original

        if _original in self.gfn_mappings:
            translated = self.gfn_mappings[_original]
            log.debug('Translating {0} to {1}', _original, translated)

        return translated
    
    payload_index = 1

    async def get_games(self):
        global local_games
        global gfn_mappings

        self.gfn_mappings = {}
        mappings_file = Path(__file__).resolve().parent.joinpath('gfn_mappings.csv')
        if mappings_file.is_file():
            with open(mappings_file, mode='r') as infile:
                reader = csv.reader(infile)
                self.gfn_mappings = {rows[0]: rows[1] for rows in reader}
                log.debug('Mappings: {0}'.format(str(self.gfn_mappings)))
        else:
            log.debug('Could not find mappings file [{0}]'.format(str(mappings_file)))

        while(True):
            try:
                    gfn_site = 'api-prod.nvidia.com'

                    if(self.payload_index == 1):
                            payload = "{apps(country:\"US\" language:\"en_US\"){numberReturned,pageInfo{endCursor,hasNextPage},items{title,sortName,variants{appStore,publisherName,id}}}}\r\n"
                    if(self.payload_index == 2):
                            payload = "{apps(country:\"US\" language:\"en_US\" after:\"NzUw\") {numberReturned,pageInfo{endCursor,hasNextPage},items{title,sortName,variants{appStore,publisherName,id}}}}\r\n"
                    if(self.payload_index == 3):
                            payload = "{apps(country:\"US\" language:\"en_US\" after:\"MTUwMA==\") {numberReturned,pageInfo{endCursor,hasNextPage},items{title,sortName,variants{appStore,publisherName,id}}}}\r\n"
                    headers = {'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9',
                        'Accept-Encoding': 'gzip, deflate',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36'}
                        
                    conn = http.client.HTTPSConnection(gfn_site, timeout=10)
                    conn.request("POST", "/gfngames/v1/gameList", payload,headers=headers)
                    res = conn.getresponse()

                    if res.status == 200:
                        data = res.read().decode("utf-8")
                        json_data = json.loads(data)
                        res.close()
                        items = json_data['data']['apps']['items']
                        for item in items:
                            name = item['title']
                            variants = item['variants']
                            for variant in variants:
                                store = variant['appStore']
                                id = variant['id']
                                gg_id = await self.gfn_convert(store, name)
                                self.gfn_games.append(gg_id)
                                self.gfn_ids[gg_id] = id
                                asyncio.sleep(4)
                    else:
                        log.error("Failure contacting GFN server, response code: {0}".format(res.status))
                    self.payload_index += 1
                    if(self.payload_index == 4):
                        break

            except ValueError as e:
                    log.error(e)
        
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
            test_title = await self.gfn_convert(game[PLATFORM], game[TITLE])
            test_title = await self.name_fix(test_title)
            game_id = ''
            if game[KEY] in self.gfn_steam:
                game_id = game[KEY].replace('steam_', 'gfn_')
            elif test_title in self.gfn_games:
                game_id = 'gfn_' + str(self.gfn_ids[test_title])
            else:
                log.debug("Not found {0}: {1} [{2}]".format(game[PLATFORM], game[TITLE], test_title))

            if game_id != '':
                log.debug("Found {0}: {1} [{2}] [{3}]".format(game[PLATFORM], game[TITLE], test_title, game_id))
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

        dir_path = os.path.dirname(os.path.realpath(__file__))
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
    create_and_run_plugin(PluginExample, sys.argv)

# run plugin event loop
if __name__ == "__main__":
    main()
