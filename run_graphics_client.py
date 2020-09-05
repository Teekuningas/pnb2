""" Contains basic way to run client side game loop
"""

import argparse
import time

from network import GraphicsClient

from graphics import initialize
from graphics import render

from game import update
from game import merge


from constants import UPDATE_INTERVAL


if __name__ == '__main__':
    """
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--ip_address')
    parser.add_argument('--port')

    cli_args = parser.parse_args()

    ip_address = '127.0.0.1'
    if cli_args.ip_address:
        ip_address = cli_args.ip_address

    port = 5555
    if cli_args.port:
        port = cli_args.port

    # Initialize graphics
    window = initialize()

    # Establish connection
    client = GraphicsClient(ip_address, port)
    print("Client ID: " + client.client_id)

    # Get initial copy of the game state
    while True:
        game = client.get_game()
        if game:
            break

    previous = time.time()
    inputs = []
    lag = 0
    while True:
        current = time.time()
        elapsed = current - previous
        previous = current
        lag += elapsed

        if not client.connection_alive:
            print("Connection dead.. Quitting..")
            break

        # Try to get game synchronized
        while lag >= UPDATE_INTERVAL:
            print("Updating game.")

            # Get official version of the game from upstream and merge
            new_game = client.get_game()
            if new_game:
                merge(game, new_game)

            update(game, [])

            lag -= UPDATE_INTERVAL

        # Render when not occupied with the update
        render(window, game, lag / UPDATE_INTERVAL)

    print("Finished.")
