###
# Copyright (c) 2010, Valentin Lorentz
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

import os
import sys
import time
import threading
import BaseHTTPServer
import supybot.conf as conf
import supybot.world as world
import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks

try:
    import sqlite3
except ImportError:
    from pysqlite2 import dbapi2 as sqlite3 # for python2.4

try:
    from supybot.i18n import PluginInternationalization
    from supybot.i18n import internationalizeDocstring
    _ = PluginInternationalization('WebStats')
except:
    _ = lambda x:x
    internationalizeDocstring = lambda x:x

DEBUG = True

testing = world.testing

def getTemplate(name):
    if sys.modules.has_key('WebStats.templates.skeleton'):
        reload(sys.modules['WebStats.templates.skeleton'])
    if sys.modules.has_key('WebStats.templates.%s' % name):
        reload(sys.modules['WebStats.templates.%s' % name])
    module = __import__('WebStats.templates.%s' % name)
    return getattr(getattr(module, 'templates'), name)

class FooException(Exception):
    pass

class HTTPHandler(BaseHTTPServer.BaseHTTPRequestHandler):
    def do_GET(self):
        output = ''
        try:
            if self.path == '/design.css':
                response = 200
                content_type = 'text/css'
                output = getTemplate('design').get(not testing)
            elif self.path == '/':
                response = 200
                content_type = 'text/html'
                output = getTemplate('index').get(not testing,
                                                 self.server.db.getChannels())
            elif self.path == '/about/':
                response = 200
                content_type = 'text/html'
                self.end_headers()
                output = getTemplate('about').get(not testing)
            elif self.path.startswith('/%s/' % _('channels')):
                response = 200
                content_type = 'text/html'
                chanName = self.path[len(_('channels'))+2:].split('/')[0]
                output = getTemplate('chan_index').get(not testing, chanName,
                                                       self.server.db)
            else:
                response = 404
                content_type = 'text/html'
                output = getTemplate('error404').get(not testing)
        except Exception as e:
            response = 500
            content_type = 'text/html'
            if output == '':
                output = '<h1>Internal server error</h1>'
                if DEBUG:
                    output += '<p>The server raised this exception: %s</p>' % \
                    repr(e)
        finally:
            self.send_response(response)
            self.send_header('Content-type', content_type)
            self.end_headers()
            self.wfile.write(output)

class WebStatsDB:
    def __init__(self):
        filename = conf.supybot.directories.data.dirize('WebStats.db')
        alreadyExists = os.path.exists(filename)
        if alreadyExists and (DEBUG or testing):
            os.remove(filename)
            alreadyExists = False
        self._conn = sqlite3.connect(filename, check_same_thread = False)
        if not alreadyExists:
            self.makeDb()

    def makeDb(self):
        cursor = self._conn.cursor()
        cursor.execute("""CREATE TABLE messages (
                          chan VARCHAR(128),
                          nick VARCHAR(128),
                          time TIMESTAMP,
                          content TEXT
                          )""")
        cursor.execute("""CREATE TABLE moves (
                          chan VARCHAR(128),
                          nick VARCHAR(128),
                          time TIMESTAMP,
                          type CHAR(4),
                          content TEXT
                          )""")
        cursor.execute("""CREATE TABLE chans_cache (
                          chan VARCHAR(128) PRIMARY KEY,
                          lines INTEGER,
                          words INTEGER,
                          chars INTEGER,
                          joins INTEGER,
                          parts INTEGER,
                          quits INTEGER
                          )""")
        cursor.execute("""CREATE TABLE nicks_cache (
                          nick VARCHAR(128) PRIMARY KEY,
                          lines INTEGER,
                          words INTEGER,
                          chars INTEGER,
                          joins INTEGER,
                          parts INTEGER,
                          quits INTEGER
                          )""")
        self._conn.commit()
        cursor.close()

    def getChannels(self):
        cursor = self._conn.cursor()
        cursor.execute("""SELECT chan FROM chans_cache""")
        results = []
        for row in cursor:
            results.append(row[0])
        cursor.close()
        return results

    def recordMessage(self, chan, nick, message):
        cursor = self._conn.cursor()
        cursor.execute("""INSERT INTO messages VALUES (?,?,?,?)""",
                       (chan, nick, time.time(), message))
        self._conn.commit()
        cursor.close()
        if DEBUG:
            self.refreshCache()

    def recordMove(self, chan, nick, type_, message=''):
        cursor = self._conn.cursor()
        cursor.execute("""INSERT INTO moves VALUES (?,?,?,?,?)""",
                       (chan, nick, time.time(), type_, message))
        self._conn.commit()
        cursor.close()
        if DEBUG:
            self.refreshCache()

    def refreshCache(self):
        cursor = self._conn.cursor()
        cursor.execute("""DELETE FROM chans_cache""")
        cursor.execute("""DELETE FROM nicks_cache""")
        cursor.close()
        tmp_chans_cache = {}
        tmp_nicks_cache = {}
        cursor = self._conn.cursor()
        cursor.execute("""SELECT * FROM messages""")
        for row in cursor:
            chan, nick, timestamp, content = row
            if not tmp_chans_cache.has_key(chan):
                tmp_chans_cache.update({chan: [0, 0, 0, 0, 0, 0]})
            tmp_chans_cache[chan][0] += 1
            tmp_chans_cache[chan][1] += len(content.split(' '))
            tmp_chans_cache[chan][2] += len(content)
            if not tmp_nicks_cache.has_key(nick):
                tmp_nicks_cache.update({nick: [0, 0, 0, 0, 0, 0]})
            tmp_nicks_cache[nick][0] += 1
            tmp_nicks_cache[nick][1] += len(content.split(' '))
            tmp_nicks_cache[nick][2] += len(content)
        cursor.close()
        cursor = self._conn.cursor()
        cursor.execute("""SELECT * FROM moves""")
        for row in cursor:
            chan, nick, timestamp, type_, content = row
            if not tmp_chans_cache.has_key(chan):
                tmp_chans_cache.update({chan: [0, 0, 0, 0, 0, 0]})
            id = {'join': 3, 'part': 4, 'quit': 5}[type_]
            tmp_chans_cache[chan][id] += 1
            tmp_nicks_cache[nick][id] += 1
        cursor.close()
        cursor = self._conn.cursor()
        for chan in tmp_chans_cache:
            data = tmp_chans_cache[chan]
            cursor.execute("INSERT INTO chans_cache VALUES(?,?,?,?,?,?,?)",
                           (chan, data[0], data[1], data[2], data[3],
                            data[4], data[5]))
        for nick in tmp_nicks_cache:
            data = tmp_nicks_cache[nick]
            cursor.execute("INSERT INTO nicks_cache VALUES(?,?,?,?,?,?,?)",
                           (nick, data[0], data[1], data[2], data[3],
                            data[4], data[5]))
        cursor.close()
        self._conn.commit()

    def getChanMainData(self, chanName):
        cursor = self._conn.cursor()
        cursor.execute("SELECT * FROM chans_cache WHERE chan=?", (chanName,))
        row = cursor.fetchone()
        if row is None:
            return None
        return (str(row[0]),) + row[1:]


class Server:
    def __init__(self, plugin):
        self.serve = True
        self._plugin = plugin
    def run(self):
        serverAddress = (self._plugin.registryValue('server.host'),
                          self._plugin.registryValue('server.port'))
        done = False
        while not done:
            time.sleep(1)
            try:
                httpd = BaseHTTPServer.HTTPServer(serverAddress, HTTPHandler)
                done = True
            except:
                pass
        print 'WebStats web server launched'
        httpd.db = self._plugin.db
        while self.serve:
            httpd.handle_request()
        httpd.server_close()
        time.sleep(1) # Let the socket be really closed


@internationalizeDocstring
class WebStats(callbacks.Plugin):
    """Add the help for "@plugin help WebStats" here
    This should describe *how* to use this plugin."""
    def __init__(self, irc):
        self.__parent = super(WebStats, self)
        callbacks.Plugin.__init__(self, irc)
        self.db = WebStatsDB()
        self._server = Server(self)
        if not world.testing:
            threading.Thread(target=self._server.run,
                             name="WebStats HTTP Server").start()

    def die(self):
        self._server.serve = False
        self.__parent.die()

    def doPrivmsg(self, irc, msg):
        channel = msg.args[0]
        if not self.registryValue('channel.enable', channel):
            return
        content = msg.args[1]
        nick = msg.prefix.split('!')[0]
        self.db.recordMessage(channel, nick, content)
    doNotice = doPrivmsg

Class = WebStats


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79: