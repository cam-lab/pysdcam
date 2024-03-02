

import os
import time
import threading
import numpy as np

from PyQt5.QtCore import QObject, pyqtSignal

import sys

from logger import logger as lg
import vframe
import gui

from udp import command_queue, TSocket
 

#-------------------------------------------------------------------------------
class TSDC_Core(QObject):

    frame_signal = pyqtSignal( int )
    
    #-------------------------------------------------------
    def __init__(self):
        super().__init__()
        
        #-----------------------------------------
        #
        #    MMR 
        #
        
        #-----------------------------------------
        #
        #    Video frame
        #
        self._pixmap = self.init_frame()
        self._roll_line = 1000
        self._k = 1
        self._queue_limit_exceed = False
        
        vframe.init_numpy()

        self._f = vframe.TVFrame()
        
        self._agc_ena = True
        
        self.org_thres = 5
        self.top_thres = 5
        self.discard   = 0.005
        
        self._kf = 0.1
        self._kp = 0.5
        self._ka = 0.5
        
        self._stim = 0
        
        self._swing = 4096.0
        
        self.IEXP_MIN = 0
        self.IEXP_MAX = 978
        self.FEXP_MIN = 3
        self.FEXP_MAX = 1599
        
        self._iexp = self.IEXP_MIN
        self._fexp = self.FEXP_MIN
        
        self._top_ref = 3800.0;
        
        self.window_histo = np.zeros( (1024), dtype=np.uint32)
        self.fframe_histo = np.zeros( (1024), dtype=np.uint32)
        
        #-----------------------------------------
        #
        #    UDP socket
        #
        self._sock = TSocket()

    #-------------------------------------------------------
    def deinit(self):
        self._sock.close()
    
    #-------------------------------------------------------
    def init_frame(self):
        return np.tile(np.arange(4095, step=32, dtype=np.uint16), [960, 10])
    
    #-------------------------------------------------------
    def agc_slot(self, checked):
        self._agc_ena = checked
        
    #-------------------------------------------------------
    def generate(self):
        time.sleep(0.04)
        self._pmap = np.right_shift( self._pixmap, 4 ).astype(dtype=np.uint8)
        self._pmap[:, self._roll_line] = 255
        if self._roll_line < 1280-1:
            self._roll_line += 1
        else:
            self._roll_line = 0

        return self._pmap

    #-----------------------------------------------------------------
    #
    #    Video frame
    #
    #-------------------------------------------------------
    def init_cam(self):
        self._wmmr( 0x41, 0x2)  # move video pipeline to bypass mode
        self._wcam( self.IEXP, self._iexp )
        self._wcam( self.FEXP, self._fexp )
        self._wcam( self.PGA, 2 )
        
    #-------------------------------------------------------
    def read(self):
        return vframe.qpipe_get_frame(self._f, self._p)

    #-------------------------------------------------------
    def display(self, pmap):
        if gui.fqueue.qsize() < 20:
            gui.fqueue.put(pmap.astype(np.uint8))
            self.frame_signal.emit(0)
            self._queue_limit_exceed = False
        else:
            if not self._queue_limit_exceed:
                lg.warning('video frame queue exceeds limit, seems GUI does not read from the queue')
            self._queue_limit_exceed = True

    #-------------------------------------------------------
    def processing(self):
        vframe.get_frame(self._f)
        pbuf = self._f.pixbuf

        self.fframe_histo.fill(0)
        self.window_histo.fill(0)
        window = np.copy(pbuf[240:720,320:960])
        org, top, scale = vframe.histogram(window, self.window_histo, self.org_thres, self.top_thres, self.discard)
        fframe_org, fframe_top, fframe_scale = vframe.histogram(pbuf, self.fframe_histo, 30, 30, 0)
        
        self._pmap = vframe.make_display_frame(pbuf)
        self.display(self._pmap)
        time.sleep(0.04)
           
    #-----------------------------------------------------------------
    #
    #    MMR command API
    #
    #-------------------------------------------------------
    def _sock_transaction(self, fun, args):
        command_queue.put( [fun, args] )
    #-------------------------------------------------------
    def send_udp(self, data):
        return self._sock.processing(data)
        
    #-------------------------------------------------------
    def _rmmr(self, *args):
        addr    = args[0]
        data    = np.array( [0x55aa, self.READ_MMR, addr, 0], dtype=np.uint16 )
        data[3] = np.bitwise_xor.reduce(data)
        res     = self._sock.processing(data)
        cs      = np.bitwise_xor.reduce(res)
        if cs:
            lg.error('incorrect udp responce')
            
        return res[3]
        
    def rmmr(self, addr):
        self._sock_transaction(self._rmmr, [addr])
        
    #-------------------------------------------------------
    def _wmmr(self, *args):
        addr    = args[0]
        data    = args[1]
        data    = np.array( [0x55aa, self.WRITE_MMR, addr, data, 0], dtype=np.uint16 )
        data[4] = np.bitwise_xor.reduce(data)
        res     = self._sock.processing(data)
        cs      = np.bitwise_xor.reduce(res)
        if cs:
            lg.error('incorrect udp responce')
        
    def wmmr(self, addr, data):
        self._sock_transaction(self._wmmr, [addr, data])
        
    #-------------------------------------------------------
    def _wcam(self, *args):
        addr = args[0]
        data = args[1]
        cmd  = self.WR | addr
        
        self._wmmr(self.SPI_CSR,  0x1); # nCS -> 0
        self._wmmr(self.SPI_DR,   cmd); # send cmd to camera
        self._wmmr(self.SPI_DR,  data); # send value to write
        self._wmmr(self.SPI_CSR,  0x0); # nCS -> 1
        
    def wcam(self, addr, data):
        self._sock_transaction(self._wcam, [addr, data])
        
    #-------------------------------------------------------
    def _rcam(self, *args):
        addr = args[0]
        cmd  = self.RD | addr;
    
        self._wmmr(self.SPI_CSR,  0x1); # nCS -> 0
        self._wmmr(self.SPI_DR,   cmd); # send cmd to camera
        self._wmmr(self.SPI_DR,     0); # transaction to take data from camera
        self._wmmr(self.SPI_CSR,  0x0); # nCS -> 1
        return self._rmmr(self.SPI_DR);
         
    #-------------------------------------------------------
    def rcam(self, addr):
        self._sock_transaction(self._rcam, [addr])
                 
#-------------------------------------------------------------------------------
class TVFrameThread(threading.Thread):

    #-------------------------------------------------------
    def __init__(self, name='VFrame Thread' ):
        super().__init__()
        self._finish_event = threading.Event()
        self.core = TSDC_Core()

    #-------------------------------------------------------
    def finish(self):
        lg.info('VFrame Thread pending to finish')
        self._finish_event.set()

    #-------------------------------------------------------
    def run(self):
        while True:
            self.core.processing()
            if self._finish_event.is_set():
                self.core.deinit()
                return

#-------------------------------------------------------------------------------

