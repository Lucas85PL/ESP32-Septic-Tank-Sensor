# Fusion - skrypt: obudowa odbiornika RX (plytka E32R28T 2.8", 50 x 86 mm)
#
# Obudowa pozioma, otwarta z tylu (plytka wkladana od tylu, przykrecana 4 wkretami do slupkow),
# okno na ekran z przodu, boczny otwor na USB-C, opcjonalna stopka (stoi samodzielnie).
#
# Uklad wspolrzednych (mm): X = szerokosc (86), Y = glebokosc (przod = Y 0, tyl = +Y), Z = wysokosc.
# Srodek plytki PCB w X=0, Z=0. Przy domyslnym ustawieniu Fusion (Z w gore) obudowa stoi na stopce,
# a przod patrzy w kierunku -Y.
#
# Zrodlo wymiarow: rysunek producenta E32R28T-1 Size V1.0 (LCDWiki).

import traceback
import adsk.core
import adsk.fusion

# ======================= PARAMETRY [mm] - mozna edytowac =======================
PCB_W, PCB_H, PCB_T = 86.0, 50.0, 1.6      # PCB: dlugosc (X), szerokosc (Z), grubosc
CLEAR = 0.4            # luz wokol PCB (z kazdej strony)
WALL = 2.0             # grubosc scianek bocznych
FRONT_T = 2.0          # grubosc plyty czolowej
GLASS_GAP = 0.2        # szczelina miedzy plyta czolowa a szyba dotyku
STACK_T = 4.0          # taśma 0,5 + LCD 2,3 + dotyk 1,2 nad frontem PCB
BACK_COMP = 5.1        # max wysokosc elementow z tylu PCB (SMD, modul ESP, zlacza)
BACK_EXTRA = 1.1       # zapas na tyle (rezerwa)

HOLE_DX, HOLE_DZ = 78.0, 42.0    # rozstaw otworow montazowych PCB (X, Z)
POST_D = 4.6           # srednica slupka (pole pod lacznik w PCB Ø4,8)
PILOT_D = 2.5          # otwor pod wkret M3 (samogwintujacy w druku 3D)
PILOT_DEPTH = 3.6      # glebokosc otworu w slupku (wkret M3 x 6 mm)

# Okno na ekran: widoczny obszar dotyku (RTP VA) 59,45 x 45,2 mm
WIN_W, WIN_H = 59.45, 45.2
MARGIN_FAR = 10.45     # odstep okna od krawedzi PCB po stronie PRZECIWNEJ do USB
MARGIN_NEAR = 16.1     # odstep okna od krawedzi PCB po stronie USB
USB_SIDE = +1          # +1 = USB po prawej (patrzac z przodu), -1 = po lewej

# Otwor na USB-C (wtyczka z oslonka)
USB_W, USB_H = 13.0, 7.4         # szerokosc (Z) i wysokosc (Y) otworu
USB_Z_CENTER = 0.0               # USB w osi plyty
USB_Y_CENTER = 9.4               # tyl PCB (7,8) + polowa zlacza (1,6)

# Stopka (obudowa stoi samodzielnie); False = sam prostopadloscian
FOOT = True
FOOT_T = 3.0
FOOT_DEPTH = 50.0      # calkowita glebokosc stopki liczona od przodu

# Dodatkowo: model plytki (osobne cialo) do kontroli dopasowania
SHOW_PCB_REFERENCE = True
# ===============================================================================


def mm(v):
    """Fusion API pracuje w cm."""
    return v / 10.0


def run(context):
    app = adsk.core.Application.get()
    ui = app.userInterface
    try:
        doc_product = app.activeProduct
        if doc_product is None or not adsk.fusion.Design.cast(doc_product):
            app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
            doc_product = app.activeProduct
        design = adsk.fusion.Design.cast(doc_product)
        root = design.rootComponent
        tbm = adsk.fusion.TemporaryBRepManager.get()
        P = adsk.core.Point3D.create
        V = adsk.core.Vector3D.create

        def box(x0, x1, y0, y1, z0, z1):
            c = P(mm((x0 + x1) / 2.0), mm((y0 + y1) / 2.0), mm((z0 + z1) / 2.0))
            obb = adsk.core.OrientedBoundingBox3D.create(
                c, V(1, 0, 0), V(0, 1, 0), mm(x1 - x0), mm(y1 - y0), mm(z1 - z0))
            return tbm.createBox(obb)

        def cyl_y(x, z, y0, y1, d):
            return tbm.createCylinderOrCone(P(mm(x), mm(y0), mm(z)), mm(d / 2.0),
                                            P(mm(x), mm(y1), mm(z)), mm(d / 2.0))

        def union(a, b):
            tbm.booleanOperation(a, b, adsk.fusion.BooleanTypes.UnionBooleanType)

        def cut(a, b):
            tbm.booleanOperation(a, b, adsk.fusion.BooleanTypes.DifferenceBooleanType)

        # --- wymiary pochodne ---
        y_pcb_front = FRONT_T + GLASS_GAP + STACK_T          # przod PCB
        y_pcb_rear = y_pcb_front + PCB_T                     # tyl PCB
        depth = y_pcb_rear + BACK_COMP + BACK_EXTRA          # glebokosc obudowy
        in_hw = PCB_W / 2.0 + CLEAR                          # polowa wnetrza (X)
        in_hh = PCB_H / 2.0 + CLEAR                          # polowa wnetrza (Z)
        out_hw = in_hw + WALL
        out_hh = in_hh + WALL

        # --- bryla zewnetrzna ---
        body = box(-out_hw, out_hw, 0, depth, -out_hh, out_hh)

        # --- stopka ---
        if FOOT:
            union(body, box(-out_hw, out_hw, 0, max(FOOT_DEPTH, depth), -out_hh - FOOT_T, -out_hh))

        # --- wnetrze (otwarte z tylu) ---
        cut(body, box(-in_hw, in_hw, FRONT_T, depth + 1.0, -in_hh, in_hh))

        # --- slupki pod otwory montazowe + otwory pod wkrety ---
        for sx in (-1, 1):
            for sz in (-1, 1):
                x = sx * HOLE_DX / 2.0
                z = sz * HOLE_DZ / 2.0
                union(body, cyl_y(x, z, FRONT_T - 0.5, y_pcb_front, POST_D))
        for sx in (-1, 1):
            for sz in (-1, 1):
                x = sx * HOLE_DX / 2.0
                z = sz * HOLE_DZ / 2.0
                cut(body, cyl_y(x, z, y_pcb_front - PILOT_DEPTH, y_pcb_front + 0.1, PILOT_D))

        # --- okno na ekran ---
        left_margin = MARGIN_FAR if USB_SIDE > 0 else MARGIN_NEAR
        win_x0 = -PCB_W / 2.0 + left_margin
        cut(body, box(win_x0, win_x0 + WIN_W, -1.0, FRONT_T + 0.5, -WIN_H / 2.0, WIN_H / 2.0))

        # --- otwor na USB ---
        usb_x0 = in_hw - 1.0 if USB_SIDE > 0 else -out_hw - 1.0
        usb_x1 = out_hw + 1.0 if USB_SIDE > 0 else -in_hw + 1.0
        cut(body, box(usb_x0, usb_x1,
                      USB_Y_CENTER - USB_H / 2.0, USB_Y_CENTER + USB_H / 2.0,
                      USB_Z_CENTER - USB_W / 2.0, USB_Z_CENTER + USB_W / 2.0))

        # --- dodanie do projektu ---
        def add_body(tmp_body, name):
            if design.designType == adsk.fusion.DesignTypes.ParametricDesignType:
                bf = root.features.baseFeatures.add()
                bf.startEdit()
                b = root.bRepBodies.add(tmp_body, bf)
                bf.finishEdit()
            else:
                b = root.bRepBodies.add(tmp_body)
            b.name = name
            return b

        add_body(body, "Obudowa_RX")

        if SHOW_PCB_REFERENCE:
            ref = box(-PCB_W / 2.0, PCB_W / 2.0, y_pcb_front, y_pcb_rear, -PCB_H / 2.0, PCB_H / 2.0)
            # szyba + LCD (LCD BL 69,2 x 50) nad frontem PCB
            union(ref, box(-34.6, 34.6, FRONT_T + GLASS_GAP, y_pcb_front, -PCB_H / 2.0, PCB_H / 2.0))
            # zlacze USB-C z tylu PCB (orientacyjnie)
            ux = PCB_W / 2.0 * USB_SIDE
            union(ref, box(min(ux - 5.0 * USB_SIDE, ux + 1.0 * USB_SIDE), max(ux - 5.0 * USB_SIDE, ux + 1.0 * USB_SIDE),
                           y_pcb_rear, y_pcb_rear + 3.2, -4.5, 4.5))
            add_body(ref, "PCB_E32R28T_ref")

        try:
            app.activeViewport.fit()
        except Exception:
            pass

        ui.messageBox("Gotowe.\n\nObudowa: %.1f x %.1f x %.1f mm (szer. x wys. x gl.)%s\n"
                      "Okno na ekran: %.2f x %.2f mm\nUSB po stronie: %s (patrzac z przodu)" % (
                          2 * out_hw, 2 * out_hh, depth,
                          (", stopka %.0f mm" % FOOT_DEPTH) if FOOT else "",
                          WIN_W, WIN_H, "prawej" if USB_SIDE > 0 else "lewej"))
    except Exception:
        if ui:
            ui.messageBox("Blad skryptu:\n" + traceback.format_exc())
