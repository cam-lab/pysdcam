#!/usr/bin/env python3
# coding: utf-8

import sys
import os
import re

import threading
import time
import subprocess
import shlex
import argparse

import numpy as np

run_path, filename = os.path.split(  os.path.abspath(__file__) )
resources_path = run_path
sys.path.append( resources_path )

sys.path.append('bin/release')

from PyQt5.Qt        import Qt
from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore    import QObject, pyqtSignal, QFileSystemWatcher
from PyQt5.QtCore    import QT_VERSION_STR, pyqtSignal

from IPython.utils.frame import extract_module_locals
from ipykernel.kernelapp import IPKernelApp

from sdc_core import *
import gui
import ipycon
from logger import logger as lg
from logger import LOG_FILE

#-------------------------------------------------------------------------------
def get_app_qt5(*args, **kwargs):
    """Create a new qt5 app or return an existing one."""
    app = QApplication.instance()
    if app is None:
        if not args:
            args = ([''],)
        app = QApplication(*args, **kwargs)
    return app

#-------------------------------------------------------------------------------
class TSDCam(QObject):

    def __init__(self, app, args):
        
        super().__init__()
        
        self.log_watcher =  QFileSystemWatcher(self)
        self.log_watcher.addPath(os.path.abspath(LOG_FILE))

        lg.info('start main window')
        self.mwin = gui.MainWindow(app, { 'sdcam' : self })
                
        self.log_watcher.fileChanged.connect(self.mwin.LogWidget.update_slot,
                                             Qt.QueuedConnection)
        
                        
        lg.info('start video frame thread')
        self.vfthread = TVFrameThread()
        self.vfthread.start()
                
        if args.console:
            ipycon.launch_jupyter_console(self.mwin.ipkernel.abs_connection_file, args.console)
                
            
        self.mwin.close_signal.connect(self.finish)
        self.vfthread.frame.frame_signal.connect(self.mwin.show_frame_slot,
                                                 Qt.QueuedConnection)
        
        
    def finish(self):
        lg.info('sdcam finishing...')
        self.vfthread.finish()
        self.vfthread.join()
        lg.info('sdcam has finished')

    def generate_frame(self):
        self.frame
        
    
#-------------------------------------------------------------------------------
def main():
    print('Qt Version: ' + QT_VERSION_STR)
    QApplication.setDesktopSettingsAware(False)

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--console', 
                        const='shell',
                        nargs='?',
                        help='launch jupyter console on program start')
    
    args = parser.parse_args()
    app  = get_app_qt5(sys.argv)

    with open( os.path.join(resources_path, 'sdcam.qss'), 'rb') as fqss:
        qss = fqss.read().decode()
        qss = re.sub(os.linesep, '', qss )
    app.setStyleSheet(qss)

    sdcam = TSDCam(app, args)

    #sys.exit( app.exec_() )
    sdcam.mwin.ipkernel.start()

#-------------------------------------------------------------------------------
if __name__ == '__main__':
    main()
    
#-------------------------------------------------------------------------------


