"""Port protokolu logow: TX event_logger.cpp (meta/rekordy) + log_sync.cpp  <->  RX txlog.cpp (handleChunk).
Kanal radiowy z gubieniem pakietow, opoznieniem ACK i zajetym odbiornikiem."""
import random

LOG_CHUNK_DATA_MAX = 224
LOG_KEEP_CYCLES = 28
LOG_CHUNK_ACK_TIMEOUT_S = 0.300
LOG_CHUNK_RETRIES = 3
LOG_SYNC_BUDGET_S = 20.0
TXLOG_MAX_RECORD = 10240
TXLOG_MAX_FILE_BYTES = 400000
OK, RESTART, REJECT, TIMEOUT = 0, 1, 2, 3
SENT, SKIPPED, ABORT = "SENT", "SKIPPED", "ABORT"


class TxStore:
    """TX: LittleFS (meta.bin + c<ID>.txt). Zapisy atomowe wg kodu (tmp+rename); meta.bin nieatomowy."""

    def __init__(self, rng):
        self.rng = rng
        self.records = {}          # id -> bytes
        self.meta = None           # dict(epoch,nextId,sentId) lub None (brak/uszkodzony)
        self.ref = None            # (value, secondsSinceRef)
        self.resume = (0, 0, 0)    # RTC TX: (epoch,id,seq) punkt wznowienia przerwanego rekordu

    def begin(self):
        if self.meta is None:                       # loadMeta() nieudane -> initMeta()
            ids = sorted(self.records)
            epoch = 0
            while epoch == 0:
                epoch = self.rng.getrandbits(32)
            self.meta = dict(epoch=epoch, nextId=(ids[-1] + 1 if ids else 1),
                             sentId=(ids[0] - 1 if ids and ids[0] > 0 else 0))
        ids = sorted(self.records)
        if ids and ids[-1] >= self.meta["nextId"]:
            self.meta["nextId"] = ids[-1] + 1

    def commit(self, payload: bytes):
        cid = self.meta["nextId"]
        self.records[cid] = payload
        self.meta["nextId"] = cid + 1
        ids = sorted(self.records)
        for i in ids[:max(0, len(ids) - LOG_KEEP_CYCLES)]:
            del self.records[i]
        return cid

    def next_unsent(self):
        for i in sorted(self.records):
            if i > self.meta["sentId"]:
                return i
        return None

    def mark_sent(self, i):
        if i > self.meta["sentId"]:
            self.meta["sentId"] = i


class RxTxLog:
    """RX: txlog.cpp::handleChunk + commitRecord. nvs = (valid, epoch, id) przezywa reset RX."""

    def __init__(self, fs_ok=True):
        self.ok = fs_ok
        self.nvs = (False, 0, 0)
        self.files = []            # lista (epoch,id,bytes) zapisana w /txlog.txt(+old)
        self.file_bytes = 0
        self.disk_full = False
        self.reboot()

    def reboot(self):              # utrata RAM (rekord w skladaniu)
        self.active = False
        self.cur_epoch = self.cur_id = self.cur_total = self.next_seq = 0
        self.rec = bytearray()

    def handle_chunk(self, epoch, cid, seq, total, data: bytes):
        """zwraca (status, nextSeq) albo None (brak ACK)"""
        if not self.ok:
            return None
        lv, le, li = self.nvs
        if lv and epoch == le and cid <= li:
            return OK, total
        if seq == 0:
            self.active, self.cur_epoch, self.cur_id, self.cur_total = True, epoch, cid, total
            self.next_seq, self.rec = 0, bytearray()
        same = self.active and epoch == self.cur_epoch and cid == self.cur_id
        if not same or seq != self.next_seq:
            return (OK if (same and seq < self.next_seq) else RESTART), (self.next_seq if same else 0)
        if len(self.rec) + len(data) > TXLOG_MAX_RECORD:
            self.active = False
            return REJECT, 0
        self.rec += data
        self.next_seq += 1
        if self.next_seq >= self.cur_total:
            saved = self._commit()
            self.active = False
            return (OK, self.cur_total) if saved else (RESTART, 0)
        return OK, self.next_seq

    def _commit(self):
        if self.disk_full:
            return False
        self.files.append((self.cur_epoch, self.cur_id, bytes(self.rec)))
        self.nvs = (True, self.cur_epoch, self.cur_id)
        return True


class Channel:
    """p_loss: prawdopodobienstwo utraty pakietu w jednym kierunku. rx_up: czy RX odpowiada.
    rx_busy_s: ile jeszcze sekund petla RX jest zablokowana (np. przerysowanie ekranu)."""

    def __init__(self, rng, p_loss=0.0, rx_up=True, rx_busy_s=0.0, p_late=0.0):
        self.rng, self.p_loss, self.rx_up, self.rx_busy_s, self.p_late = rng, p_loss, rx_up, rx_busy_s, p_late
        self.chunks_sent = 0

    def lost(self):
        return self.rng.random() < self.p_loss


def send_record(store: TxStore, rx: RxTxLog, ch: Channel, cid, t0, budget, clock):
    """port log_sync.cpp::sendRecord. clock: dict(t=sekundy aktywnosci TX). zwraca SENT/SKIPPED/ABORT."""
    data = store.records.get(cid)
    if not data:
        return SKIPPED
    total = (len(data) + LOG_CHUNK_DATA_MAX - 1) // LOG_CHUNK_DATA_MAX
    seq, restarts = 0, 0
    epoch = store.meta["epoch"]
    re_, rid, rseq = store.resume
    if re_ == epoch and rid == cid and 0 < rseq < total:
        seq = rseq                                   # wznow od miejsca przerwania
    while seq < total:
        if clock["t"] - t0 >= budget:
            store.resume = (epoch, cid, seq)
            return ABORT
        chunk = data[seq * LOG_CHUNK_DATA_MAX:(seq + 1) * LOG_CHUNK_DATA_MAX]
        if not chunk:
            return SKIPPED
        r, nxt = _send_chunk(rx, ch, epoch, cid, seq, total, chunk, clock)
        if r == OK:
            seq += 1
        elif r == RESTART and restarts < 2:
            restarts += 1
            seq = nxt if nxt < total else 0
        elif r == REJECT:
            store.resume = (0, 0, 0)
            return SKIPPED
        else:
            store.resume = (epoch, cid, seq)
            return ABORT
    store.resume = (0, 0, 0)
    return SENT


def _send_chunk(rx, ch, epoch, cid, seq, total, chunk, clock):
    for _ in range(LOG_CHUNK_RETRIES):
        ch.chunks_sent += 1
        if not ch.rx_up or ch.lost():
            clock["t"] += LOG_CHUNK_ACK_TIMEOUT_S
            continue
        ack = rx.handle_chunk(epoch, cid, seq, total, chunk)
        # RX przetwarza w loop() dopiero po zwolnieniu petli; opoznienie ACK
        delay = ch.rx_busy_s + 0.012
        if ack is None or ch.lost():
            clock["t"] += LOG_CHUNK_ACK_TIMEOUT_S
            continue
        if delay > LOG_CHUNK_ACK_TIMEOUT_S or ch.rng.random() < ch.p_late:
            clock["t"] += LOG_CHUNK_ACK_TIMEOUT_S        # ACK przyszedl za pozno (RX juz przetworzyl porcje!)
            ch.rx_busy_s = max(0.0, ch.rx_busy_s - LOG_CHUNK_ACK_TIMEOUT_S)
            continue
        clock["t"] += delay + 0.01
        ch.rx_busy_s = 0.0
        return ack[0], ack[1]
    return TIMEOUT, 0


def flush(store: TxStore, rx: RxTxLog, ch: Channel, clock, budget=LOG_SYNC_BUDGET_S):
    """port LogSync::flush. zwraca liczbe wyslanych"""
    t0 = clock["t"]
    sent = 0
    while True:
        cid = store.next_unsent()
        if cid is None:
            break
        r = send_record(store, rx, ch, cid, t0, budget, clock)
        if r == ABORT:
            return sent
        store.mark_sent(cid)
        if r == SENT:
            sent += 1
    return sent
