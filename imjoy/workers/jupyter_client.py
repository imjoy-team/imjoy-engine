"""Provide worker functions for Python 3."""
import asyncio
import logging
import sys
import traceback
import uuid

import janus

from .utils import format_traceback
from .python3_client import AsyncClient, task_worker, JOB_HANDLERS
from .python_worker import PluginConnection
from ipykernel.comm import Comm
from IPython.display import HTML
from imjoy.utils import dotdict

import os

# pylint: disable=unused-argument, redefined-outer-name

logger = logging.getLogger("jupyter_client")


def display_imjoy(plugin_id, url="https://imjoy.io/#/app", width="100%", height=650):
    iframe_html = """
    <style>
    .card {
        background: #fff;
        border-radius: 2px;
        display: inline-block;
        height: 550px;
        margin: 1rem;
        position: relative;
        width: 98%%;
        border-radius: 8px;
    }
    .card-1 {
        box-shadow: 0 1px 3px rgba(0,0,0,0.12), 0 1px 2px rgba(0,0,0,0.24);
        transition: all 0.3s cubic-bezier(.25,.8,.25,1);
    }
    .card-1:hover {
        box-shadow: 0 7px 14px rgba(0,0,0,0.25), 0 3px 3px rgba(0,0,0,0.22);
    }
    </style>
    <iframe id="iframe_%(plugin_id)s" onload="setup_imjoy_bridge()" src="%(url)s" class="card card-1" frameborder="0" width="%(width)s" height="%(height)s" style="max-width: 100%%;"></iframe>
    <script type="text/Javascript">
    function setup_imjoy_bridge(){
        const iframeEl = document.getElementById('iframe_%(plugin_id)s')
        Jupyter.notebook.kernel.comm_manager.register_target('imjoy_comm_%(plugin_id)s',
        function (comm, open_msg) {
            comm.on_msg((msg) => {
                var data = msg.content.data
                if(iframeEl&&iframeEl.contentWindow){
                    //console.log('forwarding message to iframe', data)
                    if (["initialized",
                        "importSuccess",
                        "importFailure",
                        "executeSuccess",
                        "executeFailure"
                        ].includes(data.type)) {
                        iframeEl.contentWindow.postMessage(data, '*');
                    } else {
                        iframeEl.contentWindow.postMessage({
                        type: 'message',
                        data: data
                        }, '*');
                    }
                }
            })
            var config = open_msg.content.data
            iframeEl.contentWindow.postMessage({'type': 'init_plugin', 'id': config.id, 'config': config}, '*');
            window.comm = comm;
        });
        window.addEventListener(
        "message",
        function (e) {
            if (iframeEl && iframeEl.contentWindow && e.source === iframeEl.contentWindow) {
                if (e.data.type == "message") {
                    if(e.data.data.type === 'init_connection'){
                        setTimeout(()=>{
                            var kernel = IPython.notebook.kernel;
                            function callback(out_type, out_data){
                                console.log('starting imjoy.')
                            }
                            command = 'from imjoy.workers.python_worker import PluginConnection as __plugin_connection__;__plugin_connection__.get_plugin("%(plugin_id)s").start()';
                            kernel.execute(command, {"output": callback});
                            console.log('running start');
                        }, 1000)
                        
                    }
                    else{
                        window.comm.send(e.data.data);
                    }
                    //console.log('forwarding message to python', e.data.data)
                }
            }
            e.stopPropagation();
        },
        false
        );
    }
    </script>
    """ % {
        "url": url,
        "width": width,
        "height": height,
        "plugin_id": plugin_id,
    }
    return HTML(iframe_html)


class JupyterClient(AsyncClient):
    """Represent an async socketio client."""

    # pylint: disable=too-few-public-methods
    def __init__(self, name, secret="", debug=False):
        """Set up client instance."""
        opt = dotdict(
            id=str(uuid.uuid4()), name=name, secret=secret, work_dir="", daemon=False
        )
        conn = PluginConnection(opt)
        conn.default_exit = lambda: None
        self.name = name
        super().__init__(conn, opt)
        self.comm = None
        self.loop = asyncio.get_event_loop()
        self.janus_queue = janus.Queue(loop=self.loop)
        self.queue = self.janus_queue.sync_q
        self.task_worker = task_worker

    def setup(self):
        """Set up the plugin connection."""
        logger.setLevel(logging.INFO)
        if self.opt.debug:
            logger.setLevel(logging.DEBUG)
        self.comm = Comm(
            target_name="imjoy_comm_" + self.opt.id,
            data={"name": self.name, "id": self.opt.id, "secret": self.opt.secret},
        )
        self.comm.on_msg(self.comm_plugin_message)

        def on_disconnect():
            if not self.opt.daemon:
                self.conn.exit(1)

        self.comm.on_close(on_disconnect)
        sys.stdout.flush()

    def connect(self):
        """Connect to the socketio server."""
        self.emit({"type": "initialized", "dedicatedThread": True})
        logger.info("Plugin %s initialized", self.opt.id)

    def emit(self, msg):
        """Emit a message to the socketio server."""
        self.comm.send(msg)

    def comm_plugin_message(self, msg):
        """Handle plugin message."""
        data = msg["content"]["data"]
        # if not self.conn.executed:
        #    self.emit({'type': 'message', 'data': {"type": "interfaceSetAsRemote"}})
        if data["type"] == "import":
            self.emit({"type": "importSuccess", "url": data["url"]})
        elif data["type"] == "disconnect":
            self.conn.abort.set()
            try:
                if "exit" in self.conn.interface and callable(
                    self.conn.interface["exit"]
                ):
                    self.conn.interface["exit"]()
            except Exception as exc:  # pylint: disable=broad-except
                logger.error("Error when exiting: %s", exc)
            return None
        elif data["type"] == "execute":
            if not self.conn.executed:
                self.queue.put(data)
            else:
                logger.debug("Skip execution")
                self.emit({"type": "executeSuccess"})
        elif data["type"] == "message":
            _data = data["data"]
            self.queue.put(_data)
            logger.debug("Added task to the queue")
        sys.stdout.flush()
        return None

    def start(self):
        return display_imjoy(self.opt.id, url="http://127.0.0.1:8000/#/app")
