import os
import asyncio
import uuid
import socketio

WORKSPACE_DIR = os.path.expanduser('~/ImJoyWorkspace')
# read token from file if exists
with open(os.path.join(WORKSPACE_DIR, ".token"), "r") as f:
    token = f.read()

client_id = str(uuid.uuid4())
session_id = str(uuid.uuid4())
url = 'http://localhost:9527'

NAME_SPACE = "/"

class FakeClient():
    def __init__(self, url, client_id, session_id, token):
        self.engine_info = None
        self.url = url
        self.client_id = client_id
        self.session_id = session_id
        self.token = token

    async def init(self):
        sio = socketio.AsyncClient()

        @sio.on('connect')
        async def on_connect():
            print('I\'m connected!')

        @sio.on('message')
        async def on_message(data):
            print('I received a message!')

        @sio.on('my message')
        async def on_message(data):
            print('I received a custom message!')

        @sio.on('disconnect')
        async def on_disconnect():
            print('I\'m disconnected!')

        
        await sio.connect(self.url)

        await sio.emit('register_client', {
            'id': self.client_id,
            'token': self.token,
            'base_url': self.url,
            'session_id': self.session_id
        }, namespace=NAME_SPACE,callback=self.on_registered)

    async def on_registered(self, ret):
        print('registered...')
        if 'success' in ret and ret['success']:
            self.engine_info = ret['engine_info']
            print(self.engine_info)
        else:
            print('failed to register')

    def run(self):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.init())

if __name__ == '__main__':
    client = FakeClient(url, client_id, session_id, token)
    client.run()