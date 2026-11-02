from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt


OUT = Path(__file__).with_name("Point-in-Time_Correct_Feature_Store_Paper_Summary.pptx")

NAVY = RGBColor(8, 22, 45)
PANEL = RGBColor(17, 38, 68)
PANEL_2 = RGBColor(22, 48, 82)
CYAN = RGBColor(59, 207, 219)
BLUE = RGBColor(78, 141, 255)
GREEN = RGBColor(83, 211, 151)
AMBER = RGBColor(255, 190, 92)
WHITE = RGBColor(244, 248, 255)
MUTED = RGBColor(167, 186, 211)
RED = RGBColor(255, 105, 120)


def rect(slide, x, y, w, h, fill, radius=True, line=None):
    shape_type = MSO_AUTO_SHAPE_TYPE.ROUNDED_RECTANGLE if radius else MSO_AUTO_SHAPE_TYPE.RECTANGLE
    shp = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    shp.line.color.rgb = line or fill
    return shp


def textbox(slide, x, y, w, h, text, size=12, color=WHITE, bold=False,
            font="Aptos", align=PP_ALIGN.LEFT, valign=MSO_ANCHOR.TOP,
            margin=0.04):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.clear()
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = Inches(margin)
    tf.vertical_anchor = valign
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.name = font
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color
    return box


def rich_lines(slide, x, y, w, h, lines, base_size=10.5, gap=2):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.clear()
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(0.06)
    tf.margin_top = tf.margin_bottom = Inches(0.03)
    for i, (lead, body, color) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_after = Pt(gap)
        p.level = 0
        r1 = p.add_run()
        r1.text = lead
        r1.font.name = "Aptos"
        r1.font.size = Pt(base_size)
        r1.font.bold = True
        r1.font.color.rgb = color
        r2 = p.add_run()
        r2.text = body
        r2.font.name = "Aptos"
        r2.font.size = Pt(base_size)
        r2.font.color.rgb = WHITE
    return box


def tag(slide, x, y, w, text, color):
    rect(slide, x, y, w, 0.25, color)
    textbox(slide, x, y + 0.005, w, 0.23, text, 8.2, NAVY, True,
            align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE, margin=0)


def arrow(slide, x1, y1, x2, y2, color=MUTED):
    line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    line.line.color.rgb = color
    line.line.width = Pt(1.6)
    line.line.end_arrowhead = True
    return line


prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
slide = prs.slides.add_slide(prs.slide_layouts[6])
bg = slide.background.fill
bg.solid()
bg.fore_color.rgb = NAVY

# Header
textbox(slide, 0.52, 0.27, 9.9, 0.43,
        "POINT-IN-TIME CORRECT FEATURE STORE", 23, WHITE, True)
textbox(slide, 0.54, 0.72, 9.8, 0.30,
        "Kiến thức cốt lõi từ Liu et al., PVLDB 2023 — Optimizing Data Pipelines for ML in Feature Stores",
        10.5, MUTED)
tag(slide, 10.83, 0.30, 1.92, "PAPER → THỰC THI", CYAN)

# Top architecture band
rect(slide, 0.50, 1.15, 12.33, 1.22, PANEL)
textbox(slide, 0.72, 1.28, 1.36, 0.24, "1  KIẾN TRÚC", 10, CYAN, True)

nodes = [
    (0.72, "Nguồn dữ liệu", "Batch · Streaming"),
    (2.61, "Compute engine", "Spark / SQL"),
    (4.50, "Feature catalog", "Definition · lineage"),
    (6.39, "Offline store", "Training · throughput"),
    (8.28, "Online store", "Inference · low latency"),
    (10.17, "ML consumers", "Train · Serve · Monitor"),
]
for i, (x, title, sub) in enumerate(nodes):
    rect(slide, x, 1.60, 1.55, 0.56, PANEL_2, line=BLUE if i in (3, 4) else PANEL_2)
    textbox(slide, x + 0.08, 1.67, 1.39, 0.18, title, 9.2, WHITE, True, align=PP_ALIGN.CENTER)
    textbox(slide, x + 0.05, 1.88, 1.45, 0.16, sub, 7.7, MUTED, align=PP_ALIGN.CENTER)
    if i < len(nodes) - 1:
        arrow(slide, x + 1.58, 1.88, x + 1.85, 1.88, CYAN)

# Left: PIT correctness
rect(slide, 0.50, 2.58, 4.05, 3.98, PANEL)
textbox(slide, 0.72, 2.74, 3.45, 0.26, "2  POINT-IN-TIME JOIN = HÀNG RÀO CHỐNG LEAKAGE", 10, CYAN, True)

textbox(slide, 0.76, 3.13, 0.92, 0.20, "Label row", 8.6, AMBER, True)
rect(slide, 0.74, 3.38, 0.98, 0.57, PANEL_2, line=AMBER)
textbox(slide, 0.79, 3.48, 0.88, 0.31, "user_id\nt = cutoff", 8.7, WHITE, True, align=PP_ALIGN.CENTER)

textbox(slide, 2.06, 3.13, 1.72, 0.20, "Feature events", 8.6, GREEN, True)
rect(slide, 2.04, 3.38, 1.79, 0.57, PANEL_2, line=GREEN)
textbox(slide, 2.10, 3.47, 1.67, 0.33, "t − window ≤ event_time ≤ t", 8.3, WHITE, True,
        align=PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
arrow(slide, 1.73, 3.67, 2.01, 3.67, CYAN)

rect(slide, 0.74, 4.18, 3.48, 0.48, RGBColor(24, 55, 79), line=GREEN)
textbox(slide, 0.84, 4.26, 3.28, 0.28,
        "JOIN theo entity key + chọn trạng thái gần nhất không vượt cutoff",
        9.0, WHITE, True, align=PP_ALIGN.CENTER)

rich_lines(slide, 0.74, 4.84, 3.47, 1.39, [
    ("Đúng thời gian: ", "feature phải tồn tại tại thời điểm dự đoán.", GREEN),
    ("Đúng cửa sổ: ", "aggregate chỉ đọc [t − W, t].", GREEN),
    ("Giữ label rows: ", "left PIT join vẫn giữ entity không có feature match.", BLUE),
    ("Sai ⇒ ", "future information lọt vào train set, offline score tăng giả và lệch khi serving.", RED),
], base_size=9.4, gap=3)

# Middle: optimization workflow
rect(slide, 4.75, 2.58, 4.12, 3.98, PANEL)
textbox(slide, 4.97, 2.74, 3.65, 0.26, "3  FEATHRPO: TỐI ƯU PIPELINE PIT", 10, CYAN, True)

steps = [
    (3.16, "MATCHER", "So định nghĩa mới với feature đã materialize; kiểm tra source còn hợp lệ."),
    (3.88, "REWRITER", "Sinh plan tương đương: full/partial containment; chỉ tính phần delta chưa xử lý."),
    (4.60, "COST ESTIMATOR", "Chọn original hoặc rewritten plan theo lượng data scan ước tính."),
    (5.32, "COMPUTE + CATALOG", "Chạy Spark; đăng ký feature, storage path, statistics và layout mới."),
]
for idx, (y, head, body) in enumerate(steps):
    rect(slide, 5.00, y, 3.56, 0.56, PANEL_2, line=[AMBER, BLUE, GREEN, CYAN][idx])
    textbox(slide, 5.13, y + 0.08, 1.10, 0.17, head, 8.4, [AMBER, BLUE, GREEN, CYAN][idx], True)
    textbox(slide, 6.14, y + 0.07, 2.28, 0.39, body, 7.9, WHITE)
    if idx < 3:
        arrow(slide, 6.78, y + 0.58, 6.78, y + 0.70, MUTED)

textbox(slide, 5.02, 6.06, 3.52, 0.30,
        "Ví dụ: đã có window 30d → feature 40d chỉ tính thêm delta [t−40, t−30).",
        8.6, AMBER, True, align=PP_ALIGN.CENTER)

# Right: data layout + findings
rect(slide, 9.07, 2.58, 3.76, 3.98, PANEL)
textbox(slide, 9.29, 2.74, 3.25, 0.26, "4  DATA LAYOUT + COST MODEL", 10, CYAN, True)
rich_lines(slide, 9.27, 3.14, 3.30, 1.55, [
    ("Partition theo time: ", "year/month/day/hour để partition pruning giảm scan.", BLUE),
    ("Cost proxy: ", "data scanned − lợi ích layout; xét bytes bỏ qua, selectivity và số partition.", GREEN),
    ("Cardinality: ", "KLL sketches ước lượng quantile/selectivity cho append-only data.", AMBER),
    ("Global selection: ", "BIP chọn đúng 1 layout/source dưới ngân sách rewrite B.", CYAN),
], base_size=9.0, gap=3)

rect(slide, 9.27, 4.82, 3.30, 1.43, RGBColor(22, 55, 76), line=GREEN)
textbox(slide, 9.44, 4.94, 2.96, 0.22, "KẾT QUẢ & GIỚI HẠN", 9.2, GREEN, True, align=PP_ALIGN.CENTER)
rich_lines(slide, 9.44, 5.24, 2.94, 0.88, [
    ("Tốc độ: ", "tới 3.0× vs Feathr; 1.4–2.5× trên PIT implementations khác.", GREEN),
    ("Phạm vi paper: ", "offline store + O1 reuse + O2 layout; incremental refresh/scheduling/engine selection chưa giải quyết.", AMBER),
], base_size=8.7, gap=4)

# Bottom takeaway bar
rect(slide, 0.50, 6.74, 12.33, 0.47, RGBColor(15, 56, 76), line=CYAN)
textbox(slide, 0.72, 6.82, 11.90, 0.25,
        "TAKEAWAY  •  Correctness trước: entity key + event time + cutoff + window.  •  Efficiency sau: reuse materialization + time partitioning + cost-based plan/layout.",
        9.4, WHITE, True, align=PP_ALIGN.CENTER)
textbox(slide, 0.55, 7.25, 12.20, 0.12,
        "Nguồn: Liu et al., PVLDB 16(13), 2023 · DOI 10.14778/3625054.3625060",
        6.8, MUTED, align=PP_ALIGN.RIGHT, margin=0)

prs.save(OUT)
print(OUT)
