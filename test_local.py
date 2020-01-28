# wait_for_connection(port=9527, token='1234') # for interactive debugging
# start_imjoy_client() # for jupyter notebook
# start_server(port=9888, token='1234') # for deploying plugins

config = {
  "name": "Untitled Plugin",
  "type": "native-python",
  "version": "0.1.0",
  "description": "[TODO: describe this plugin with one sentence.]",
  "tags": [],
  "ui": "",
  "cover": "",
  "flags": [],
  "icon": "extension",
  "api_version": "0.1.7",
  "env": "",
  "permissions": [],
  "requirements": [],
  "dependencies": []
}

from imjoy import api

def setup():
    pass

def run():
    api.alert('hello')

api.export({'run': run, 'setup': setup}, config=config)

# api.summary()
