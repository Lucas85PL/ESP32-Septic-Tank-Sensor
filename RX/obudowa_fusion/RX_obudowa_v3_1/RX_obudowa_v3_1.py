# Fusion - skrypt: obudowa odbiornika RX v3.1 (plytka E32R28T 2.8", 50 x 86 mm)
#
# Zmiany wzgledem v3.1: glebokosc +5 mm (49,6 mm), plecki FLUSH z tylem obudowy (bez obrzeza),
# pogłebienia pod lebki wkretow w pleckach.
#
# Prostopadloscian, stoi sam (bez stopki), USB z LEWEJ strony (patrzac na wyswietlacz,
# w programie DISPLAY_ROTATION 3).
#
# Mocowanie:
#   * PLYTKA: jak w v1.0 - 4 slupki przy froncie, wkrety M3 x 6 od tylu PCB (bez zmian)
#   * PLECKI: osobne 4 slupki w WEWNETRZNYCH ROGACH obudowy (z tylu, 6 x 6 mm), wkrety M3 x 8
#     wkrecane w te slupki. Wkrety NIE przechodza przez plytke, nic nie dociska plytki.
#
# Wkladanie plytki (rogowe slupki pleckow przeszkadzaja - plytke trzeba wlozyc po skosie):
#   1. Plytke z wyswietlaczem nachyl o ok. 35-40 stopni wokol DLUZSZEJ osi (jedna dluga krawedz
#      do przodu), wsun przez tylny otwor miedzy slupki do glebokosci ok. 20 mm
#      (mierzone od przodu obudowy do przodu plytki).
#   2. Potem stopniowo prostuj plytke i dosuwaj ja do przednich slupkow.
#   3. Przykrec plytke 4 x M3 x 6 od tylu (przez otwory w PCB w przednie slupki), zaloz plecki.
# Geometria (wysokosc wnetrza, polozenie slupkow) dobrana symulacja ruchu, kat przejscia 36 st.
#
# Uklad wspolrzednych (mm): X = szerokosc (86), Y = glebokosc (przod = Y 0, tyl = +Y), Z = wysokosc.
# Srodek plytki PCB w X=0, Z=0.
#
# Zrodlo wymiarow: rysunek producenta E32R28T-1 Size V1.0 (LCDWiki).

import traceback
import adsk.core
import adsk.fusion

# ======================= PARAMETRY [mm] - mozna edytowac =======================
PCB_W, PCB_H, PCB_T = 86.0, 50.0, 1.6      # PCB: dlugosc (X), szerokosc (Z), grubosc
CLEAR_X = 0.4          # luz wokol PCB w osi X (na strone)
CLEAR_Z = 2.0          # luz wokol PCB w osi Z (na strone) - potrzebny do wkladania po skosie
WALL = 2.0             # grubosc scianek
FRONT_T = 2.0          # grubosc plyty czolowej
GLASS_GAP = 0.2        # szczelina miedzy plyta czolowa a szyba dotyku
STACK_T = 4.0          # tasma 0,5 + LCD 2,3 + dotyk 1,2 nad frontem PCB

# Przednie slupki pod PLYTKE (jak w v1.0)
HOLE_DX, HOLE_DZ = 78.0, 42.0    # rozstaw otworow montazowych PCB (X, Z)
POST_D = 4.6           # srednica slupka (pole wokol otworu w PCB Ø4,8)
PILOT_D = 2.5          # otwor pod wkret M3 (samogwintujacy)
PILOT_DEPTH = 3.6      # glebokosc otworu (wkret M3 x 6 mm)

# Tylne slupki pod PLECKI (w rogach wnetrza)
REAR_POST_SZ = 6.0     # przekroj slupka rogowego (kwadrat)
REAR_POST_FRONT_Y = 41.0   # polozenie przodu slupkow (od przodu obudowy) - NIE zmniejszaj bez ponownej symulacji
REAR_POST_LEN = 6.0    # dlugosc slupka
REAR_PILOT_D = 2.5     # otwor pod wkret M3 w slupku rogowym
REAR_PILOT_DEPTH = 5.0 # glebokosc (wkret M3 x 8 mm)

# Plecki
COVER_T = 2.6          # grubosc pleckow
COVER_CLEAR = 0.15     # luz pleckow wzgledem scianek wnetrza (na strone)
SCREW_HOLE_D = 3.4     # otwor przelotowy na wkret M3 w pleckach
REAR_RIM = 0.0         # obrzeze za pleckami; 0 = plecki rowno z tylem obudowy (flush)
CBORE_D = 6.0          # pogłebienie pod lebek wkreta w pleckach
CBORE_DEPTH = 1.8      # (lebek M3 ~2 mm wystaje najwyzej ~0,2 mm; najlepiej lebek niski/gniazdowy)

# Okno na ekran: widoczny obszar dotyku (RTP VA) 59,45 x 45,2 mm
WIN_W, WIN_H = 59.45, 45.2
MARGIN_FAR = 10.45     # odstep okna od krawedzi PCB po stronie PRZECIWNEJ do USB
MARGIN_NEAR = 16.1     # odstep okna od krawedzi PCB po stronie USB
USB_SIDE = -1          # -1 = USB po LEWEJ (patrzac z przodu), +1 = po prawej

# Otwor na USB-C (wtyczka z oslonka)
USB_W, USB_H = 13.0, 7.4
USB_Z_CENTER = 0.0
USB_Y_CENTER = 9.4     # tyl PCB (7,8) + polowa zlacza (1,6)

# Stopka - przy tej glebokosci niepotrzebna; True dodaje plyte pod spodem
FOOT = False
FOOT_T = 3.0
FOOT_DEPTH = 70.0

SHOW_PCB_REFERENCE = True   # model plytki (osobne cialo) do kontroli dopasowania
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
        y_pcb_front = FRONT_T + GLASS_GAP + STACK_T            # przod PCB
        y_pcb_rear = y_pcb_front + PCB_T                       # tyl PCB
        y_rp0 = REAR_POST_FRONT_Y                              # przod slupkow rogowych
        y_cover_in = y_rp0 + REAR_POST_LEN                     # przod pleckow = tyl slupkow
        depth = y_cover_in + COVER_T + REAR_RIM                # glebokosc obudowy
        in_hw = PCB_W / 2.0 + CLEAR_X                          # polowa wnetrza (X)
        in_hh = PCB_H / 2.0 + CLEAR_Z                          # polowa wnetrza (Z)
        out_hw = in_hw + WALL
        out_hh = in_hh + WALL
        front_pts = [(sx * HOLE_DX / 2.0, sz * HOLE_DZ / 2.0) for sx in (-1, 1) for sz in (-1, 1)]
        rear_pts = [(sx * (in_hw - REAR_POST_SZ / 2.0), sz * (in_hh - REAR_POST_SZ / 2.0))
                    for sx in (-1, 1) for sz in (-1, 1)]

        # ================= OBUDOWA =================
        body = box(-out_hw, out_hw, 0, depth, -out_hh, out_hh)

        if FOOT:
            union(body, box(-out_hw, out_hw, 0, max(FOOT_DEPTH, depth), -out_hh - FOOT_T, -out_hh))

        # wnetrze (otwarte z tylu)
        cut(body, box(-in_hw, in_hw, FRONT_T, depth + 1.0, -in_hh, in_hh))

        # przednie slupki pod plytke + otwory pod wkrety
        for (x, z) in front_pts:
            union(body, cyl_y(x, z, FRONT_T - 0.5, y_pcb_front, POST_D))
        for (x, z) in front_pts:
            cut(body, cyl_y(x, z, y_pcb_front - PILOT_DEPTH, y_pcb_front + 0.1, PILOT_D))

        # tylne slupki rogowe pod plecki (kwadrat w rogu, wchodzi 0,5 mm w sciane dla pewnego polaczenia)
        for sx in (-1, 1):
            for sz in (-1, 1):
                xa, xb = sorted((sx * (in_hw - REAR_POST_SZ), sx * (in_hw + 0.5)))
                za, zb = sorted((sz * (in_hh - REAR_POST_SZ), sz * (in_hh + 0.5)))
                union(body, box(xa, xb, y_rp0, y_cover_in, za, zb))
        for (x, z) in rear_pts:
            cut(body, cyl_y(x, z, y_cover_in - REAR_PILOT_DEPTH, y_cover_in + 0.1, REAR_PILOT_D))

        # okno na ekran
        left_margin = MARGIN_FAR if USB_SIDE > 0 else MARGIN_NEAR
        win_x0 = -PCB_W / 2.0 + left_margin
        cut(body, box(win_x0, win_x0 + WIN_W, -1.0, FRONT_T + 0.5, -WIN_H / 2.0, WIN_H / 2.0))

        # otwor na USB
        usb_x0 = in_hw - 1.0 if USB_SIDE > 0 else -out_hw - 1.0
        usb_x1 = out_hw + 1.0 if USB_SIDE > 0 else -in_hw + 1.0
        cut(body, box(usb_x0, usb_x1,
                      USB_Y_CENTER - USB_H / 2.0, USB_Y_CENTER + USB_H / 2.0,
                      USB_Z_CENTER - USB_W / 2.0, USB_Z_CENTER + USB_W / 2.0))

        # ================= PLECKI =================
        cover = box(-(in_hw - COVER_CLEAR), in_hw - COVER_CLEAR, y_cover_in, y_cover_in + COVER_T,
                    -(in_hh - COVER_CLEAR), in_hh - COVER_CLEAR)
        for (x, z) in rear_pts:
            cut(cover, cyl_y(x, z, y_cover_in - 0.1, y_cover_in + COVER_T + 0.1, SCREW_HOLE_D))
            cut(cover, cyl_y(x, z, y_cover_in + COVER_T - CBORE_DEPTH, y_cover_in + COVER_T + 0.1, CBORE_D))

        # ================= DODANIE DO PROJEKTU =================
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

        add_body(body, "Obudowa_RX_v3_1")
        add_body(cover, "Plecki_RX_v3_1")

        if SHOW_PCB_REFERENCE:
            ref = box(-PCB_W / 2.0, PCB_W / 2.0, y_pcb_front, y_pcb_rear, -PCB_H / 2.0, PCB_H / 2.0)
            union(ref, box(-34.6, 34.6, FRONT_T + GLASS_GAP, y_pcb_front, -PCB_H / 2.0, PCB_H / 2.0))
            ux = PCB_W / 2.0 * USB_SIDE
            union(ref, box(min(ux - 5.0 * USB_SIDE, ux + 1.0 * USB_SIDE), max(ux - 5.0 * USB_SIDE, ux + 1.0 * USB_SIDE),
                           y_pcb_rear, y_pcb_rear + 3.2, -4.5, 4.5))
            add_body(ref, "PCB_E32R28T_ref")

        try:
            app.activeViewport.fit()
        except Exception:
            pass

        ui.messageBox("Gotowe (v3.1).\n\nObudowa: %.1f x %.1f x %.1f mm (szer. x wys. x gl.)\n"
                      "Okno na ekran: %.2f x %.2f mm\nUSB po stronie: %s (patrzac z przodu)\n\n"
                      "Wkrety: plytka 4 x M3 x 6 mm, plecki 4 x M3 x 8 mm\n\n"
                      "Plytke wkladaj po skosie (ok. 35-40 st. wokol dluzszej osi), patrz opis na poczatku skryptu.\n"
                      "Druk: obudowa przodem do stolu lub dolem; plecki plasko." % (
                          2 * out_hw, 2 * out_hh, depth, WIN_W, WIN_H,
                          "prawej" if USB_SIDE > 0 else "lewej"))
    except Exception:
        if ui:
            ui.messageBox("Blad skryptu:\n" + traceback.format_exc())
