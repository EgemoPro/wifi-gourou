"""
╔══════════════════════════════════════════════════════════════╗
║  voucher_pdf.py — Générateur tickets WiFi imprimables       ║
║  WIFIZONE · 32 tickets par page · A4 · 4 colonnes x 8 lignes║
╚══════════════════════════════════════════════════════════════╝

MODÈLE PERSONNALISABLE — Modifier uniquement la section
"CONFIGURATION DU MODÈLE" ci-dessous.

CHAQUE VOUCHER (dict) :
  name         : code/username affiché en grand
  password     : mot de passe (si user_mode="member")
  profile      : nom du profil RouterOS
  user_mode    : "voucher" | "member"
  time_limit   : durée affichée (ex: "1 jour")
  data_limit   : limite data (ex: "2 GB") — "" = illimitée
  price        : prix (ex: "500 FCFA") — "" = masqué
  login_url    : URL portail pour QR code — "" = pas de QR
  generated_at : date affichée en bas
"""

import io, logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

logger = logging.getLogger("voucher_pdf")

# ╔══════════════════════════════════════════════════════════════╗
# ║  CONFIGURATION DU MODÈLE — TOUT CE QUI EST ICI EST        ║
# ║  MODIFIABLE SANS TOUCHER AU RESTE DU CODE                  ║
# ╚══════════════════════════════════════════════════════════════╝

# ── Grille ────────────────────────────────────────────────────
MARGIN_MM = 8       # Marges feuille A4 (mm)
COLS      = 4       # Colonnes — 4 x 8 = 32 tickets/page
ROWS      = 8       # Lignes
GAP_H_MM  = 2       # Espace horizontal entre tickets (zone découpe)
GAP_V_MM  = 2       # Espace vertical entre tickets (zone découpe)

# ── Couleurs ──────────────────────────────────────────────────
COLOR_HEADER_HEX  = "#1A56A0"   # Barre de titre
COLOR_CODE_BG_HEX = "#EEF6FF"   # Fond du code/username
COLOR_TEXT_HEX    = "#1A1A2E"   # Texte principal
COLOR_LABEL_HEX   = "#555555"   # Labels (DURÉE, PRIX...)
COLOR_BORDER_HEX  = "#BBBBBB"   # Bordure de découpe

# ── Couleurs de fond par profil ───────────────────────────────
PROFILE_COLORS_HEX = {
    "1h":      "#DBEAFE",
    "2h":      "#DBEAFE",
    "3h":      "#DCFCE7",
    "6h":      "#FEF9C3",
    "12h":     "#FFEDD5",
    "1jour":   "#F3E8FF",
    "1day":    "#F3E8FF",
    "7jours":  "#DCFCE7",
    "7days":   "#DCFCE7",
    "30jours": "#FFE4E6",
    "30days":  "#FFE4E6",
    "default": "#F8F8F8",
}

# ── Typographie ───────────────────────────────────────────────
FONT_HEADER      = "Helvetica-Bold"
FONT_HEADER_SIZE = 6
FONT_CODE        = "Helvetica-Bold"
FONT_CODE_SIZE   = 10    # Réduire si code > 8 caractères
FONT_VALUE       = "Helvetica-Bold"
FONT_VALUE_SIZE  = 6
FONT_LABEL       = "Helvetica"
FONT_LABEL_SIZE  = 5
FONT_NUMBER_SIZE = 5
FONT_DATE_SIZE   = 4.5

# ── Éléments affichés ─────────────────────────────────────────
SHOW_TICKET_NUMBER = True    # Numéro #001 en haut à droite
SHOW_DATE          = True    # Date de génération en bas gauche
SHOW_SITE_NAME     = True    # Nom du site dans le header
SHOW_PRICE         = True    # Prix
SHOW_DATA_LIMIT    = True    # Data limit (si non vide)
SHOW_QR_DEFAULT    = True    # QR code (URL de connexion)

# ── Autres ────────────────────────────────────────────────────
HEADER_RATIO    = 0.25    # Hauteur header = 25% du ticket
CORNER_RADIUS_MM = 1.5   # Arrondi des coins (mm)
QR_SIZE_MM      = 10     # Taille QR code (mm)
DASH_BORDER     = True   # True = pointillés | False = plein
DASH_ON, DASH_OFF = 2, 2
BORDER_WIDTH    = 0.4

# ╔══════════════════════════════════════════════════════════════╗
# ║  FIN CONFIGURATION — NE PAS MODIFIER EN DESSOUS            ║
# ╚══════════════════════════════════════════════════════════════╝

PAGE_W, PAGE_H = A4
MARGIN   = MARGIN_MM  * mm
GAP_H    = GAP_H_MM   * mm
GAP_V    = GAP_V_MM   * mm
TICKET_W = (PAGE_W - 2*MARGIN - (COLS-1)*GAP_H) / COLS
TICKET_H = (PAGE_H - 2*MARGIN - (ROWS-1)*GAP_V) / ROWS
HEADER_H = TICKET_H * HEADER_RATIO
CORNER_R = CORNER_RADIUS_MM * mm
QR_SIZE  = QR_SIZE_MM * mm
PAD      = 2 * mm
PER_PAGE = COLS * ROWS

C_HEADER  = colors.HexColor(COLOR_HEADER_HEX)
C_CODE_BG = colors.HexColor(COLOR_CODE_BG_HEX)
C_TEXT    = colors.HexColor(COLOR_TEXT_HEX)
C_LABEL   = colors.HexColor(COLOR_LABEL_HEX)
C_BORDER  = colors.HexColor(COLOR_BORDER_HEX)
C_WHITE   = colors.white
PROFILE_COLORS = {k: colors.HexColor(v) for k,v in PROFILE_COLORS_HEX.items()}


def _bg(profile):
    key = profile.lower().replace(" ","")
    for k,v in PROFILE_COLORS.items():
        if k in key: return v
    return PROFILE_COLORS["default"]


def _qr(data):
    try:
        import qrcode
        qr = qrcode.QRCode(version=1, box_size=3, border=1)
        qr.add_data(data); qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO(); img.save(buf, format="PNG"); buf.seek(0)
        return ImageReader(buf)
    except Exception as e:
        logger.warning(f"QR non généré : {e}"); return None


def _draw_ticket(c, x, y, voucher, config, show_qr, number):
    w, h = TICKET_W, TICKET_H
    profile   = voucher.get("profile","default")
    user_mode = voucher.get("user_mode","voucher")

    # Fond
    c.setFillColor(_bg(profile))
    c.roundRect(x, y, w, h, CORNER_R, fill=1, stroke=0)

    # Bordure découpe
    c.setStrokeColor(C_BORDER)
    c.setLineWidth(BORDER_WIDTH)
    if DASH_BORDER: c.setDash(DASH_ON, DASH_OFF)
    c.roundRect(x, y, w, h, CORNER_R, fill=0, stroke=1)
    c.setDash()

    # Header
    c.setFillColor(C_HEADER)
    c.roundRect(x, y+h-HEADER_H, w, HEADER_H, CORNER_R, fill=1, stroke=0)
    c.rect(x, y+h-HEADER_H, w, HEADER_H/2, fill=1, stroke=0)

    if SHOW_SITE_NAME:
        c.setFillColor(C_WHITE)
        c.setFont(FONT_HEADER, FONT_HEADER_SIZE)
        c.drawCentredString(x+w/2, y+h-HEADER_H*0.55,
                            config.get("site_name","WIFIZONE").upper())

    if SHOW_TICKET_NUMBER:
        c.setFillColor(colors.HexColor("#AACCFF"))
        c.setFont("Helvetica", FONT_NUMBER_SIZE)
        c.drawRightString(x+w-PAD, y+h-HEADER_H*0.55, f"#{number:03d}")

    # Corps
    cy = y+h-HEADER_H-1.5*mm

    c.setFillColor(C_LABEL)
    c.setFont(FONT_LABEL, FONT_LABEL_SIZE)
    label = "CODE WIFI" if user_mode=="voucher" else "USERNAME"
    c.drawCentredString(x+w/2, cy-2.5*mm, label)

    code   = voucher.get("name","--------")
    code_h = 5.5*mm
    code_y = cy-2.5*mm-code_h-0.5*mm
    c.setFillColor(C_CODE_BG)
    c.roundRect(x+PAD, code_y, w-2*PAD, code_h, 1*mm, fill=1, stroke=0)
    c.setFillColor(C_HEADER)
    c.setFont(FONT_CODE, FONT_CODE_SIZE)
    c.drawCentredString(x+w/2, code_y+1.5*mm, code)
    cy = code_y-1*mm

    if user_mode=="member":
        pwd = voucher.get("password","")
        c.setFillColor(C_LABEL); c.setFont(FONT_LABEL, FONT_LABEL_SIZE)
        c.drawString(x+PAD, cy-2*mm, "MOT DE PASSE :")
        c.setFillColor(C_TEXT); c.setFont(FONT_VALUE, FONT_VALUE_SIZE)
        c.drawString(x+PAD, cy-4.5*mm, pwd)
        cy -= 6*mm

    c.setStrokeColor(C_BORDER); c.setLineWidth(0.2)
    sep_y = cy-1*mm
    c.line(x+PAD, sep_y, x+w-PAD, sep_y)

    info_y  = sep_y-2*mm
    col2_x  = x+w/2

    def kv(lbl, val, lx, ly):
        c.setFillColor(C_LABEL); c.setFont(FONT_LABEL, FONT_LABEL_SIZE)
        c.drawString(lx, ly, lbl)
        c.setFillColor(C_TEXT); c.setFont(FONT_VALUE, FONT_VALUE_SIZE)
        c.drawString(lx, ly-3.5*mm, val)

    kv("DUREE", voucher.get("time_limit", profile), x+PAD, info_y)
    if SHOW_PRICE and voucher.get("price"):
        kv("PRIX", voucher["price"], col2_x, info_y)
    if SHOW_DATA_LIMIT and voucher.get("data_limit"):
        kv("DATA MAX", voucher["data_limit"], x+PAD, info_y-5*mm)

    if show_qr and voucher.get("login_url"):
        qr_img = _qr(voucher["login_url"])
        if qr_img:
            c.drawImage(qr_img, x+w-QR_SIZE-PAD, y+1.5*mm,
                        QR_SIZE, QR_SIZE, preserveAspectRatio=True)

    if SHOW_DATE:
        gen = voucher.get("generated_at", datetime.utcnow().strftime("%d/%m/%Y"))
        c.setFillColor(C_LABEL); c.setFont("Helvetica", FONT_DATE_SIZE)
        c.drawString(x+PAD, y+1.0*mm, gen)


def generate_voucher_pdf(vouchers: List[Dict[str,Any]], config: dict,
                         output_path: str,
                         show_qr: bool = SHOW_QR_DEFAULT) -> str:
    c = canvas.Canvas(output_path, pagesize=A4)
    c.setTitle(f"Tickets WiFi — {config.get('site_name','WIFIZONE')}")
    c.setAuthor("WIFIZONE Agent")
    total = len(vouchers)
    logger.info(f"PDF : {total} tickets · grille {COLS}x{ROWS} · "
                f"ticket {TICKET_W/mm:.1f}x{TICKET_H/mm:.1f}mm")
    for page_start in range(0, total, PER_PAGE):
        for idx, v in enumerate(vouchers[page_start:page_start+PER_PAGE]):
            col = idx % COLS
            row = idx // COLS
            tx  = MARGIN + col*(TICKET_W+GAP_H)
            ty  = PAGE_H - MARGIN - (row+1)*TICKET_H - row*GAP_V
            _draw_ticket(c, tx, ty, v, config, show_qr, page_start+idx+1)
        c.showPage()
    c.save()
    logger.info(f"PDF sauvegardé : {output_path}")
    return output_path
