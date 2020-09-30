""" Handles socket messaging for Client and Server
"""
import socket
import json
import string
import secrets
import time
import sys

import threading

from constants import SOCKET_MESSAGE_LENGTH
from constants import JOIN_TIMEOUT
from constants import ID_SUFFIX_LENGTH
from constants import N_PLAYER_CLIENTS_NEEDED


class Server:
    """ Handles server side socket connections
    """
    def __init__(self, ip_address='127.0.0.1', port=5555):
        """
        """
        self.clients = {}
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((ip_address, port))
        self.sock.listen()

        print("Waiting for connections, server started..")

        t = threading.Thread(target=self.look_for_joins)
        t.start()

        while True:
            if self.n_player_clients_connected() == N_PLAYER_CLIENTS_NEEDED:
                break

    def threaded_client(self, conn, client_idx):
        """
        """
        client_state = {'conn': conn, 
                        'type': None, 
                        'messages': [],
                        'messages_lock': threading.Lock(),
                        'id': None, 
                        'connected': True, 
                        'initialized': False,
                        'active': True}
        self.clients[client_idx] = client_state

        buffer_ = ""
        beginning = time.time()
        done = False
        while not done:

            if time.time() - beginning > JOIN_TIMEOUT:
                print("Closed connection to " + str(client_idx))
                client_state['connected'] = False
                client_state['initialized'] = True
                conn.close()
                return

            try:
                buffer_, messages = self.read_messages(conn, buffer_, client_idx)
                for message in messages:
                    message_dict = json.loads(message)

                    if message_dict.get('type', '') == 'PLAYER_JOIN':
                        if self.n_player_clients_joined() < N_PLAYER_CLIENTS_NEEDED:

                            secure_str = ''.join((secrets.choice(string.ascii_letters) 
                                                  for i in range(ID_SUFFIX_LENGTH)))
                            player_idx = self.n_player_clients_joined()
                            id_ = str(player_idx) + '#' + secure_str

                            client_state['type'] = 'player'
                            client_state['id'] = id_

                            message_dict = {'type': 'PLAYER_JOIN_APPROVED',
                                            'value': id_}
                            conn.send(json.dumps(message_dict).encode('UTF-8') + 
                                      '$'.encode('utf-8'))
                            done = True
                        else:
                            client_state['connected'] = False
                            client_state['initialized'] = True

                            message_dict = {'type': 'PLAYER_JOIN_DECLINED'}
                            conn.send(json.dumps(message_dict).encode('UTF-8') + 
                                      '$'.encode('utf-8'))
                            conn.close()
                            return

                    elif message_dict.get('type', '') == 'PLAYER_REJOIN':
                        rejoin_key = message_dict.get('value', '')

                        # check if valid old client state exists and mark it as inactive
                        found = False
                        for idx, state in self.clients.items():
                            if state.get('type') == 'player' and state.get('active') == True:
                                if state.get('connected') == False:
                                    if state.get('id') == rejoin_key:
                                        state['active'] = False
                                        found = True

                        if found:
                            client_state['type'] = 'player'
                            client_state['id'] = rejoin_key

                            message_dict = {'type': 'PLAYER_REJOIN_APPROVED',
                                            'value': rejoin_key}
                            conn.send(json.dumps(message_dict).encode('UTF-8') + 
                                      '$'.encode('utf-8'))
                            done = True
                        else:
                            client_state['connected'] = False
                            client_state['initialized'] = True

                            message_dict = {'type': 'PLAYER_REJOIN_DECLINED'}
                            conn.send(json.dumps(message_dict).encode('UTF-8') + 
                                      '$'.encode('utf-8'))
                            conn.close()
                            return

                    elif message_dict.get('type', '') == 'GRAPHICS_JOIN':
                        secure_str = ''.join((secrets.choice(string.ascii_letters) 
                                              for i in range(ID_SUFFIX_LENGTH)))
                        id_ = 'x#' + secure_str

                        client_state['type'] = 'graphics'
                        client_state['id'] = id_

                        message_dict = {'type': 'GRAPHICS_JOIN_APPROVED',
                                        'value': id_}
                        conn.send(json.dumps(message_dict).encode('UTF-8') + 
                                  '$'.encode('utf-8'))
                        done = True

            except Exception as exc:
                print(str(exc))
                print("Lost connection to " + str(client_idx))
                client_state['connected'] = False
                client_state['initialized'] = True
                conn.close()
                return

        # if survived here, mark as initialized
        client_state['initialized'] = True

        # and continue to post-initialization communication
        while True:
            try:
                buffer_, messages = self.read_messages(conn, buffer_, client_idx)

                if messages:
                    self.clients[client_idx]['messages_lock'].acquire()
                    self.clients[client_idx]['messages'].extend(messages)
                    self.clients[client_idx]['messages_lock'].release()

            except Exception as exc:
                print(str(exc))
                print("Lost connection to " + str(client_idx))
                client_state['connected'] = False
                conn.close()
                return

    def look_for_joins(self):
        """ Actively, in a thread, look for client joining
        """
        while True:
            conn, addr = self.sock.accept()
            print("Negotiating with: " + str(addr))

            keys = list(self.clients.keys())
            if keys:
                client_idx = max(self.clients.keys()) + 1
            else:
                client_idx = 0

            t = threading.Thread(target=self.threaded_client, args=(conn, client_idx))
            t.start()

            # start processing next client only after the current has 
            # been marked as initialized
            while True:
                if client_idx in self.clients:
                    if self.clients[client_idx].get('initialized'):
                        break

    def n_player_clients_connected(self):
        """ How many player clients connected 
        """
        count = 0
        for state in list(self.clients.values()):
            if state.get('type', '') == 'player':
                if state.get('connected') == True:
                    count += 1
        return count


    def n_player_clients_joined(self):
        """ How many players have been connected
        """
        count = 0
        for state in list(self.clients.values()):
            if state.get('type', '') == 'player':
                count += 1
        return count

    def handle_disconnections(self):
        """ Check for disconnections and if disconnection detected,
        inform all clients and block until the same player has joined back
        """

        # check if any player has disconnected
        disconnections = False
        for state in list(self.clients.values()):
            if state.get('type') == 'player' and state.get('active') == True:
                if state.get('connected') == False:
                    disconnections = True
                    break

        if not disconnections:
            return

        print("Player has disconnected.. Taking a break..")

        # if yes, send message of break to every client
        message_dict = {'type': 'DISCONNECTION_BREAK'}
        for state in list(self.clients.values()):
            if state.get('connected') == True:
                state['conn'].send(
                    json.dumps(message_dict).encode('UTF-8') + 
                    '$'.encode('utf-8'))

        while True:
            if self.n_player_clients_connected() == N_PLAYER_CLIENTS_NEEDED:
                break

        print("Player has rejoined.. Continuing.")

    def read_messages(self, conn, buffer_, client_idx):
        """
        """
        message = conn.recv(SOCKET_MESSAGE_LENGTH)
        buffer_ = buffer_ + message.decode('utf-8')

        if not message:
            raise Exception("Disconnected by " + str(client_idx))
        else:
            parts = []
            # $ is used as a message separator
            while '$' in buffer_:
                idx = buffer_.index('$')
                parts.append(buffer_[:idx])
                buffer_ = buffer_[idx+1:]

        return buffer_, parts

    def send_game(self, game):
        """ Send "official" game from server to clients
        """
        message_dict = {'type': 'GAME',
                        'value': game}

        for state in list(self.clients.values()):
            try:
                # Use $ as message separator
                state['conn'].send(json.dumps(message_dict).encode('UTF-8') + 
                                   '$'.encode('utf-8'))
            except OSError:
                continue

    def get_inputs(self):
        """ Get inputs from clients to server
        """
        inputs = [[] for idx in range(N_PLAYER_CLIENTS_NEEDED)]
        
        for state in list(self.clients.values()):
            if state.get('type') == 'player' and state.get('connected'):
                player_inputs = []

                input_idx = int(state.get('id').split('#')[0])

                state['messages_lock'].acquire()
                for message_idx, message in enumerate(state.get('messages')):
                    message_dict = json.loads(message)
                    if message_dict['type'] == 'INPUTS':
                        state['messages'].pop(message_idx)
                        for val in message_dict['value']:
                            if val not in player_inputs:
                                player_inputs.append(val)
                state['messages_lock'].release()

                inputs[input_idx] = player_inputs
        return inputs


class Client:
    """ Handles client side socket connections
    """

    def __init__(self, ip_address, port, rejoin_key):
        """
        """
        self.messages = []
        self.messages_lock = threading.Lock()
        self.client_id = None
        self.sock = None
        self.connection_alive = False

        def threaded_connection():
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                self.sock = sock
                sock.connect((ip_address, port))

                self.connection_alive = True

                buffer_ = ""
                while True:
                    try:
                        message = sock.recv(SOCKET_MESSAGE_LENGTH)
                        buffer_ = buffer_ + message.decode('utf-8')

                        if not message:
                            print("Disconnected.")
                            break
                        else:
                            parts = []

                            while '$' in buffer_:
                                idx = buffer_.index('$')
                                parts.append(buffer_[:idx])
                                buffer_ = buffer_[idx+1:]

                            if parts:
                                self.messages_lock.acquire()
                                self.messages.extend(parts)
                                self.messages_lock.release()

                    except Exception as exc:
                        print(str(exc))
                        break

                self.connection_alive = False
                print("Lost connection to server.")

        # Run client-side socket messaging in thread

        t = threading.Thread(target=threaded_connection)
        t.start()

        while True:
            if not self.connection_alive:
                continue
            self.join_game(rejoin_key)
            return self

    def get_game(self):
        """ Get upstream game from server to client side
        """
        game = None

        self.messages_lock.acquire()
        for message_idx, message in enumerate(self.messages):
            message_dict = json.loads(message)
            if message_dict['type'] == 'GAME':
                self.messages.pop(message_idx)
                game = message_dict['value']
        self.messages_lock.release()

        return game


class PlayerClient(Client):
    """ Handles server side socket connections for player client
    """

    def __init__(self, ip_address='127.0.0.1', port=5555, rejoin_key=None):
        """
        """
        Client.__init__(self, ip_address, port, rejoin_key)

    def join_game(self, rejoin_key=None):
        """
        """
        if rejoin_key:
            message_dict = {'type': 'PLAYER_REJOIN',
                            'value': rejoin_key}
        else:
            message_dict = {'type': 'PLAYER_JOIN'}

        try:
            # Use $ as a message separator
            self.sock.send(json.dumps(message_dict).encode('UTF-8') + 
                           '$'.encode('utf-8'))
        except OSError:
            if rejoin_key:
                raise Exception('Could not send PLAYER_REJOIN message to the server')
            else:
                raise Exception('Could not send PLAYER_JOIN message to the server')

        done = False
        while not done:

            self.messages_lock.acquire()
            for message_idx, message in enumerate(self.messages):
                message_dict = json.loads(message)
                if message_dict['type'] == 'PLAYER_REJOIN_APPROVED':
                    self.messages.pop(message_idx)
                    self.client_id = message_dict['value']
                    done = True
                elif message_dict['type'] == 'PLAYER_REJOIN_DECLINED':
                    self.messages.pop(message_idx)
                    raise Exception('PLAYER_REJOIN DECLINED BY SERVER')
                elif message_dict['type'] == 'PLAYER_JOIN_APPROVED':
                    self.messages.pop(message_idx)
                    self.client_id = message_dict['value']
                    done = True
                elif message_dict['type'] == 'PLAYER_JOIN_DECLINED':
                    self.messages.pop(message_idx)
                    raise Exception('PLAYER_JOIN DECLINED BY SERVER')
            self.messages_lock.release()

    def send_inputs(self, inputs):
        """ Send inputs from client to server side
        """
        message_dict = {'type': 'INPUTS',
                        'value': inputs}

        try:
            # Use $ as a message separator
            self.sock.send(json.dumps(message_dict).encode('UTF-8') + 
                           '$'.encode('utf-8'))
        except OSError:
            pass


class GraphicsClient(Client):
    """ Handles server side connections for graphics client
    """
    def __init__(self, ip_address='127.0.0.1', port=5555, rejoin_key=None):
        """
        """
        Client.__init__(self, ip_address, port, rejoin_key)

    def join_game(self, rejoin_key=None):
        """
        """
        message_dict = {'type': 'GRAPHICS_JOIN'}
        try:
            # Use $ as a message separator
            self.sock.send(json.dumps(message_dict).encode('UTF-8') + 
                           '$'.encode('utf-8'))
        except OSError:
            raise Exception('Could not send GRAPHICS_JOIN message to the server')

        done = False
        while not done:
            self.messages_lock.acquire()
            for message_idx, message in enumerate(self.messages):
                message_dict = json.loads(message)
                if message_dict['type'] == 'GRAPHICS_JOIN_APPROVED':
                    self.messages.pop(message_idx)
                    self.client_id = message_dict['value']
                    done = True
                elif message_dict['type'] == 'GRAPHICS_JOIN_DECLINED':
                    raise Exception('GRAPHICS_JOIN DECLINED BY SERVER')
            self.messages_lock.release()

