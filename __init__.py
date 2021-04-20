import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))

from framework import app
try:
    from qbittorrent import Client
except:
    try:
        os.system("{} install python-qbittorrent".format(app.config['config']['pip']))
        from qbittorrent import Client
    except:
        pass

try:
    import transmissionrpc
except:
    try:
        os.system("{} install transmissionrpc".format(app.config['config']['pip']))
        import transmissionrpc
    except:
        pass

    
from .plugin import blueprint, menu, plugin_load, plugin_unload, plugin_info, process_telegram_data
from .logic import Logic
from .model import ModelDownloaderItem

