#!/usr/bin/python

from subprocess import Popen, PIPE
import ConfigParser
import os
import socket
import select
import sys
import time
import string
from StringIO import StringIO

default_config = """
[remote]
port = 9001
password = bobblefish
listenaddr = 127.0.0.1

[java]
server   = ./minecraft_server.jar
heap_max = 1024M
heap_min = 1024M
"""

class Mineremote:
   def __init__(self):
      self.log('Hello, world!')

      if not self.load_config():
         self.log('Failed loading the configuration file, this is fatal.')
         exit()
      else:
         self.log('Loaded configuration!')
         self.start_listening()

      try:
         self.start_minecraft_server()
         self.mainloop()
      except Exception, e:
         self.log_exception("__init__() -> mainloop()", e)
      except KeyboardInterrupt:
         self.log('Ctrl-C? Really! Maaaaaan...')
         self.server_stdin.write('stop\n')

      self.log('Exit!')

   def log(self, msg):
      print '[REMOTE] %s' % msg

   def log_server(self, msg):
      print '[SERVER] %s' % msg

   def log_exception(self, function, exception):
      self.log('-----------------------')
      self.log('Caught exception!')
      self.log('Function: %s' % function)
      self.log('Exception: %s' % exception)
      self.log('-----------------------')

   def start_listening(self):
      self.log('Starting to listen on port %d...' % self.port)
      self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
      self.server_socket.bind((self.listenaddr, self.port))
      self.server_socket.listen(10)

   def clear_peer(self, peer):
      try:
         self.clients.pop(peer)
         self.outputs.remove(peer)
         peer.close()

         self.log('Connection count: %d' % len(self.clients))
      except Exception, e:
         self.log_exception('clear_peer()', e)

   def mainloop(self):
      self.clients = dict({})

      while True:
         try:
            readready, writeready, exceptready = select.select(
                  self.outputs, 
                  self.inputs, 
                  [],
                  1.0)
         except Exception, e:
            self.log_exception("mainloop() > select()", e)
            continue

         if readready == []:
            for i in self.clients:
               if (time.time() - self.clients[i]['connected']) > 15 \
                     and not self.clients[i]['auth']:
                  self.log('Killed %s:%s: No password within 15 seconds' 
                        % socket.getnameinfo(i.getpeername(), 0))
                  self.clear_peer(i)
                  break
         else:
            for s in readready:
               if s == sys.stdin:
                  line = s.readline()
                  self.server_stdin.write('%s' % line)

               elif s == self.server_socket:
                  (client, address) = self.server_socket.accept()
                  self.outputs.append(client)

                  if self.password:
                     auth = False
                  else:
                     auth = True

                  self.clients[client] = dict(
                           {
                              'socket': client,
                              'auth': auth,
                              'connected': int(time.time())
                           }
                        )
   
                  self.log('Got a new connection from %s:%s' 
                        % socket.getnameinfo(address, 0))
                  self.log('Connection count: %d' % len(self.clients))
   
               elif s in self.clients:
                  # Data from a client
                  try:
                     buf = s.recv(256)
   
                     if buf == '':
                        # buffer is empty, client died!
                        self.log('Lost connection from %s:%s'
                              % socket.getnameinfo(s.getpeername(), 0))
      
                        self.clear_peer(s)
                     else:
                        if not self.clients[s]['auth']:
                           if buf.rstrip() != self.password:
                              self.send_peer(s, '- Bad password, sorry >:O')   
                              self.log('Killed %s:%s: Bad password' % socket.getnameinfo(s.getpeername(), 0))
                              self.clear_peer(s)
                           else:
                              self.clients[s]['auth'] = True
                              self.send_peer(s, '+ Access granted, welcome')
         
                              continue
      
                        # Valid data!
                        (host, port) = socket.getnameinfo(s.getpeername(), 0)
                        self.log('<%s:%s> %s' % (host, port, buf.rstrip()))
      
                        if buf.rstrip() == '.close':
                           self.log('Client %s:%s left me' % (host, port))
                           self.send_peer(s, '+ Bye')
                           self.clear_peer(s)
                        else:
                           self.server_stdin.write('%s\n' % buf.rstrip())
                  except Exception, e:
                     self.clear_peer(s)
                     self.log_exception('mainloop() > clientdata', e)

               elif s == self.server.stderr or s == self.server.stdout:
                  line = s.readline().rstrip()
                  if line == '':
                     self.do_exit()
                     return True
  
                  self.log_server(line)
  
                  for i in self.clients:
                     if self.clients[i]['auth']:
                        if self.send_peer(i, line) == 0:
                           self.log('%s:%s appears dead, removing'
                                 % socket.getnameinfo(i.getpeername(), 0))
   
                           self.clear_peer(i)

   def do_exit(self):
      self.server_socket.close()
         
   def send_peer(self, peer, what):
      try:
         return peer.send('%s\r\n' % what)
      except Exception, e:
         self.log_exception('send_peer()', e)
   
   def start_minecraft_server(self):
      self.log('Starting Minecraft server...')
      server_startcmd = [
               "java", 
               "-Xmx%s" % self.java_heapmax, 
               "-Xms%s" % self.java_heapmin,
               "-jar",
               self.server_jar,
               "nogui"
            ]

      self.log(' > %s' % string.join(server_startcmd, " "))

      self.server = Popen(
            server_startcmd,
            stdout = PIPE,
            stderr = PIPE,
            stdin  = PIPE
            )

      self.outputs = [
            self.server_socket,
            self.server.stderr,
            self.server.stdout,
            sys.stdin
            ]
      self.inputs  = []

      self.server_stdin = self.server.stdin

   def load_config(self):
      try:
         config = ConfigParser.ConfigParser()
         config.readfp(StringIO(default_config))
      except ConfigParser.Error, cpe:
         self.log_exception('load_config()', cpe)
         return False

      if os.path.isfile('mineremote.ini'):
         self.log('Found configuration, loading...')

         try:
            config.read('mineremote.ini')
         except ConfigParser.Error, cpe:
            self.log_exception('load_config()', cpe)
            return False
      else:
         self.log('Could not find an existing configuration, creating it...')

         try:
            config_file = open('mineremote.ini', 'w')
            config.write(config_file)
         except Exception, e:
            self.log_exception('load_config()', e)
            return False
         finally:
            config_file.close()

      try:
         self.port     = config.getint('remote', 'port')
         self.password = config.get('remote', 'password')

         if self.password == '':
            self.password = None

         self.listenaddr = config.get('remote', 'listenaddr')

         self.server_jar = config.get('java', 'server')

         self.java_heapmax = config.get('java', 'heap_max')
         self.java_heapmin = config.get('java', 'heap_min')
      except Exception, e:
         self.log_exception('load_config()', e)
         return False

      return True


srv = Mineremote()
