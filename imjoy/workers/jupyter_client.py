"""Provide worker functions for Python 3."""
import asyncio
import logging
import sys
import traceback

import janus

from .utils import format_traceback
from .python3_client import AsyncClient
from .python_worker import PluginConnection
from ipykernel.comm import Comm
from IPython.display import HTML
from imjoy.utils import dotdict

import os

# pylint: disable=unused-argument, redefined-outer-name

logger = logging.getLogger("jupyter_client")


def show_imjoy(client_id, url="https://imjoy.io/#/app", width="100%", height=650):
    """Show ImJoy in the output cell."""
    iframe_html = """
    <style>
    .card {
        background: #fff;
        border-radius: 2px;
        display: inline-block;
        height: 550px;
        margin: 1rem;
        position: relative;
        width: calc(100%% - 3ex);
        border-radius: 4px;
    }
    .card-1 {
        box-shadow: 0 1px 2px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24);
        transition: all 0.3s cubic-bezier(.25,.8,.25,1);
    }
    .card-1:hover {
        box-shadow: 0 6px 10px rgba(0,0,0,0.25), 0 3px 3px rgba(0,0,0,0.22);
    }
    </style>
    <iframe id="iframe_%(client_id)s" onload="setup_imjoy_bridge()" src="%(url)s" class="card card-1" frameborder="0" width="%(width)s" height="%(height)s" style="max-width: 100%%;"></iframe>
    <script type="text/Javascript">
    (function(){
        class PostMessageIO{
            constructor(iframeEl){
                this.plugins = {}
                this._callbacks = {}
                this.iframeEl = iframeEl
                window.addEventListener(
                    "message",
                    (e)=>{
                        if(e.data.pio_connect){
                            if(this._callbacks['connect']){
                                for(let cb of this._callbacks['connect']){ 
                                    try{
                                        cb()
                                    }
                                    catch(e){
                                        console.error(e)
                                    }
                                }
                            }
                        }
                        else if(e.data.pio_disconnect){
                            if(this._callbacks['disconnect']){
                                for(let cb of this._callbacks['disconnect']){ 
                                    try{
                                        cb()
                                    }
                                    catch(e){
                                        console.error(e)
                                    }
                                }
                            }
                        }
                        else{
                            if (iframeEl && iframeEl.contentWindow && e.source === iframeEl.contentWindow) {
                                if(e.data.channel && this._callbacks[e.data.channel]){
                                    for(let cb of this._callbacks[e.data.channel]){
                                        try{
                                            cb(e.data)
                                        }
                                        catch(e){
                                            console.error(e)
                                        }
                                    }
                                }
                            }
                        }
                    },
                    false
                );
            }
            
            emit(channel, data, transferables) {
                data.channel = channel
                this.iframeEl.contentWindow.postMessage(
                    data,
                    "*",
                    transferables
                );
            }

            on(channel, callback){
                if(this._callbacks[channel]){
                    this._callbacks[channel].push(callback)
                }
                else{
                    this._callbacks[channel] = [callback]
                }
            }
            
            off(channel, callback){
                if(this._callbacks[channel]){
                    for( var i = 0; i < this._callbacks[channel].length; i++){ 
                        if ( this._callbacks[channel][i] === callback) {
                            this._callbacks[channel].splice(i, 1); 
                        }
                    }
                }
            }
        }
        window.PostMessageIO = PostMessageIO;
    })()

    function setup_imjoy_bridge(){
        var kernel = IPython.notebook.kernel;
        command = 'from imjoy.workers.jupyter_client import JupyterClient;JupyterClient.recover_client("%(client_id)s")';
        kernel.execute(command);
        console.log(command)

        const iframeEl = document.getElementById('iframe_%(client_id)s')
        const pio = new PostMessageIO(iframeEl);
        let _connected_comm = null;
        function add_plugin(plugin, _connected_comm){
            const id = plugin.id
            pio.on("message_to_plugin_" + id, (data)=>{
                _connected_comm.send(data.data);
            })
            _connected_comm.on_msg((msg) => {
                var data = msg.content.data
                if (["initialized",
                    "importSuccess",
                    "importFailure",
                    "executeSuccess",
                    "executeFailure"
                    ].includes(data.type)) {
                    pio.emit("message_from_plugin_" + id, data);
                } else {
                    pio.emit("message_from_plugin_" + id, { type: 'message', data: data });
                }
                
            })
        }
        Jupyter.notebook.kernel.comm_manager.register_target(
            'imjoy_comm_%(client_id)s',
            function (comm, open_msg) {
                _connected_comm = comm;
                for(let k in pio.plugins){
                    add_plugin(pio.plugins[k], _connected_comm)
                }
                //var config = open_msg.content.data
                //pio.emit("message_from_plugin_" + id, {'type': 'init_plugin', 'id': config.id, 'config': config});
            }
        )

        pio.on('connect', ()=>{
            console.log('pio connected.')
        })

        pio.on('init_plugin', (plugin_config)=>{
            //id, type, config
            pio.plugins[plugin_config.id] = plugin_config
            if(_connected_comm){
                add_plugin(plugin_config, _connected_comm)
            }

            var kernel = IPython.notebook.kernel;
            command = 'from imjoy.workers.python_worker import PluginConnection as __plugin_connection__;__plugin_connection__.add_plugin("'+plugin_config.id+'", "%(client_id)s").start()';
            kernel.execute(command);
        });
    }
    </script>
    """ % {
        "url": url,
        "width": width,
        "height": height,
        "client_id": client_id,
    }
    return HTML(iframe_html)


class JupyterClient(AsyncClient):
    """Represent an async socketio client."""

    @staticmethod
    def recover_client(id):
        if JupyterClient._clients.get(id):
            return JupyterClient._clients.get(id)
        else:
            return JupyterClient(id)

    # pylint: disable=too-few-public-methods
    def __init__(self, id=None):
        """Set up client instance."""
        super().__init__(id)
        self.comm = None

    def setup(self, conn):
        """Set up the plugin connection."""

        self.comm = self.comm or Comm(
            target_name="imjoy_comm_" + self.id, data={"id": self.id}
        )

        def on_disconnect():
            if not conn.opt.daemon:
                conn.exit(1)

        def emit(msg):
            """Emit a message to the socketio server."""
            self.comm.send(msg)

        def comm_plugin_message(msg):
            """Handle plugin message."""

            data = msg["content"]["data"]
            # emit({'type': 'logging', 'details': data})

            # if not self.conn.executed:
            #    self.emit({'type': 'message', 'data': {"type": "interfaceSetAsRemote"}})
            if data["type"] == "import":
                emit({"type": "importSuccess", "url": data["url"]})
            elif data["type"] == "disconnect":
                conn.abort.set()
                try:
                    if "exit" in conn.interface and callable(conn.interface["exit"]):
                        conn.interface["exit"]()
                except Exception as exc:  # pylint: disable=broad-except
                    logger.error("Error when exiting: %s", exc)
            elif data["type"] == "execute":
                if not conn.executed:
                    self.queue.put(data)
                else:
                    logger.debug("Skip execution")
                    emit({"type": "executeSuccess"})
            elif data["type"] == "message":
                _data = data["data"]
                self.queue.put(_data)
                logger.debug("Added task to the queue")

        self.comm.on_msg(comm_plugin_message)
        self.comm.on_close(on_disconnect)

        conn.default_exit = lambda: None
        conn.emit = emit

        emit({"type": "initialized", "dedicatedThread": True})
        logger.info("Plugin %s initialized", conn.opt.id)

    # def run_forever(self, conn):
    #     self.loop.create_task(self.task_worker(conn, self.queue, logger, conn.abort))

    def start(
        self,
        name="Untitled Plugin",
        workspace="default",
        imjoy_url="https://imjoy.io",
        width="100%",
        height=650,
    ):
        """Show ImJoy in the output cell."""
        return show_imjoy(
            self.id,
            url=f"{imjoy_url}/#/app?jupyter_plugin={name}&workspace={workspace}",
            width=width,
            height=height,
        )
