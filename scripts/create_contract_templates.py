"""
Generate 4 CVLPOS leaseback contract templates as .docx files.
Uses python-docx to create Word documents with {{ variable }} placeholders
that docxtpl will render later.
"""
from docx import Document
from docx.shared import Pt, Cm, Emu
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
import os

OUTPUT_DIR = "/Users/yasudaosamu/Desktop/codes/auction/templates/contracts"
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def set_run_font(run, size_pt=10.5, bold=False, font_name="游明朝"):
    """Configure a run with Japanese-friendly font settings."""
    run.font.size = Pt(size_pt)
    run.bold = bold
    run.font.name = font_name
    # Set East-Asian font via XML so Word picks it up correctly
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = r_pr.makeelement(qn("w:rFonts"), {})
        r_pr.insert(0, r_fonts)
    r_fonts.set(qn("w:eastAsia"), font_name)


def add_title(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(24)
    run = p.add_run(text)
    set_run_font(run, size_pt=16, bold=True)


def add_heading_text(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(12)
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    set_run_font(run, size_pt=12, bold=True)


def add_body(doc, text):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(4)
    run = p.add_run(text)
    set_run_font(run, size_pt=10.5)
    return p


def add_blank_line(doc):
    doc.add_paragraph()


def add_signature_block(doc):
    add_blank_line(doc)
    add_blank_line(doc)
    add_body(doc, "甲 署名: ____________________  印")
    add_blank_line(doc)
    add_body(doc, "乙 署名: ____________________  印")


def set_default_margins(doc):
    for section in doc.sections:
        section.top_margin = Cm(2.5)
        section.bottom_margin = Cm(2.5)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)


# ---------------------------------------------------------------------------
# 1. 匿名組合契約書 (TK Agreement)
# ---------------------------------------------------------------------------

def create_tk_agreement():
    doc = Document()
    set_default_margins(doc)

    add_title(doc, "匿名組合契約書")

    # Parties
    add_heading_text(doc, "当事者")
    add_body(doc, "甲（営業者）: {{ party_a_name }}")
    add_body(doc, "住所: {{ party_a_address }}")
    add_body(doc, "代表者: {{ party_a_representative }}")
    add_blank_line(doc)
    add_body(doc, "乙（匿名組合員）: {{ party_b_name }}")
    add_body(doc, "住所: {{ party_b_address }}")
    add_body(doc, "代表者: {{ party_b_representative }}")
    add_blank_line(doc)
    add_body(doc, "契約日: {{ contract_date }}")

    # Article 1
    add_heading_text(doc, "第1条（目的）")
    add_body(doc,
        "甲は、乙から出資を受けた金員をもって、商用車両のリースバック事業"
        "（以下「本件事業」という）を営み、その営業から生ずる利益を乙に分配する。")

    # Article 2
    add_heading_text(doc, "第2条（出資）")
    add_body(doc, "乙は、本契約に基づき、金{{ purchase_price }}円を甲に出資する。")
    add_body(doc,
        "出資金は、本契約締結後速やかに甲の指定する口座に振り込む方法により払い込む。")

    # Article 3
    add_heading_text(doc, "第3条（利益分配）")
    add_body(doc,
        "甲は、本件事業から生じる利益を、目標利回り{{ target_yield_rate }}に基づき乙に分配する。")
    add_body(doc,
        "分配は月額{{ monthly_lease_fee }}円のリース料収入を原資とする。")
    add_body(doc,
        "分配金は毎月末日に計算し、翌月{{ payment_day }}日までに乙の指定口座に振り込む。")

    # Article 4
    add_heading_text(doc, "第4条（契約期間）")
    add_body(doc, "本契約の期間は、{{ lease_term_months }}ヶ月とする。")
    add_body(doc,
        "開始日: {{ lease_start_date }}  終了日: {{ lease_end_date }}")

    # Article 5
    add_heading_text(doc, "第5条（対象車両）")
    add_body(doc, "メーカー: {{ vehicle_maker }}")
    add_body(doc, "車種: {{ vehicle_model }}")
    add_body(doc, "年式: {{ vehicle_year }}年")
    add_body(doc, "走行距離: {{ vehicle_mileage }}")
    add_body(doc, "車台番号: {{ vehicle_chassis_number }}")
    add_body(doc, "登録番号: {{ vehicle_registration_number }}")

    # Article 6
    add_heading_text(doc, "第6条（業務執行）")
    add_body(doc,
        "甲は、善良なる管理者の注意をもって本件事業の業務を執行する。"
        "乙は、甲の業務執行に対し指示を行い、又はこれに参加することはできない。")

    # Article 7
    add_heading_text(doc, "第7条（解約・終了）")
    add_body(doc,
        "本契約は、契約期間の満了をもって終了する。"
        "やむを得ない事由がある場合は、3ヶ月前の書面通知により中途解約できるものとする。")

    # Article 8
    add_heading_text(doc, "第8条（秘密保持）")
    add_body(doc,
        "甲及び乙は、本契約に関して知り得た相手方の秘密情報を、"
        "相手方の事前の書面による承諾なく第三者に開示又は漏洩してはならない。")

    # Article 9
    add_heading_text(doc, "第9条（管轄裁判所）")
    add_body(doc,
        "本契約に関する紛争については、東京地方裁判所を第一審の専属的合意管轄裁判所とする。")

    add_body(doc,
        "本契約の成立を証するため、本書2通を作成し、甲乙記名押印のうえ各1通を保有する。")

    add_signature_block(doc)

    path = os.path.join(OUTPUT_DIR, "tk_agreement.docx")
    doc.save(path)
    print(f"Created: {path}")


# ---------------------------------------------------------------------------
# 2. 車両売買契約書 (Sales Agreement)
# ---------------------------------------------------------------------------

def create_sales_agreement():
    doc = Document()
    set_default_margins(doc)

    add_title(doc, "車両売買契約書")

    add_heading_text(doc, "当事者")
    add_body(doc, "甲（売主）: {{ party_a_name }} ({{ party_a_address }})")
    add_body(doc, "代表者: {{ party_a_representative }}")
    add_blank_line(doc)
    add_body(doc, "乙（買主）: {{ party_b_name }} ({{ party_b_address }})")
    add_body(doc, "代表者: {{ party_b_representative }}")
    add_blank_line(doc)
    add_body(doc, "契約日: {{ contract_date }}")

    # Article 1
    add_heading_text(doc, "第1条（売買の合意）")
    add_body(doc,
        "甲は、乙に対し、末尾記載の車両を金{{ purchase_price }}円（消費税別）にて売却し、"
        "乙はこれを買い受ける。")

    # Article 2
    add_heading_text(doc, "第2条（対象車両）")
    add_body(doc, "メーカー: {{ vehicle_maker }}")
    add_body(doc, "車種: {{ vehicle_model }} / 年式: {{ vehicle_year }}年")
    add_body(doc, "走行距離: {{ vehicle_mileage }}")
    add_body(doc, "架装: {{ vehicle_body_type }}")
    add_body(doc, "車台番号: {{ vehicle_chassis_number }}")
    add_body(doc, "登録番号: {{ vehicle_registration_number }}")

    # Article 3
    add_heading_text(doc, "第3条（代金支払い）")
    add_body(doc,
        "乙は、本契約締結後速やかに売買代金を甲の指定する口座に振り込むものとする。")
    add_body(doc,
        "振込先: {{ payment_bank_name }} {{ payment_branch_name }} "
        "{{ payment_account_type }} {{ payment_account_number }}")

    # Article 4
    add_heading_text(doc, "第4条（名義変更・引渡し）")
    add_body(doc,
        "甲は、売買代金の受領を確認後、速やかに車両の名義変更手続を行い、"
        "乙に対して車両を引き渡すものとする。")
    add_body(doc,
        "名義変更に要する費用は、乙の負担とする。")

    # Article 5
    add_heading_text(doc, "第5条（瑕疵担保）")
    add_body(doc,
        "甲は、引渡し後{{ warranty_months }}ヶ月間、対象車両の隠れた瑕疵について担保責任を負う。"
        "ただし、乙の故意又は過失による損傷についてはこの限りでない。")

    # Article 6
    add_heading_text(doc, "第6条（危険負担）")
    add_body(doc,
        "車両の引渡し前に生じた滅失・毀損の危険は甲が負担し、"
        "引渡し後の危険は乙が負担する。")

    # Article 7
    add_heading_text(doc, "第7条（契約解除）")
    add_body(doc,
        "甲又は乙が本契約に違反し、相当の期間を定めて催告したにもかかわらず"
        "是正されない場合、相手方は本契約を解除することができる。")

    # Article 8
    add_heading_text(doc, "第8条（管轄裁判所）")
    add_body(doc,
        "本契約に関する紛争については、東京地方裁判所を第一審の専属的合意管轄裁判所とする。")

    add_body(doc,
        "本契約の成立を証するため、本書2通を作成し、甲乙記名押印のうえ各1通を保有する。")

    add_signature_block(doc)

    path = os.path.join(OUTPUT_DIR, "sales_agreement.docx")
    doc.save(path)
    print(f"Created: {path}")


# ---------------------------------------------------------------------------
# 3. マスターリース契約書 (Master Lease)
# ---------------------------------------------------------------------------

def create_master_lease():
    doc = Document()
    set_default_margins(doc)

    add_title(doc, "マスターリース契約書")

    add_heading_text(doc, "当事者")
    add_body(doc, "甲（貸人）: {{ party_a_name }}")
    add_body(doc, "住所: {{ party_a_address }}")
    add_body(doc, "代表者: {{ party_a_representative }}")
    add_blank_line(doc)
    add_body(doc, "乙（借人）: {{ party_b_name }}")
    add_body(doc, "住所: {{ party_b_address }}")
    add_body(doc, "代表者: {{ party_b_representative }}")
    add_blank_line(doc)
    add_body(doc, "契約日: {{ contract_date }}")

    # Article 1
    add_heading_text(doc, "第1条（リースの合意）")
    add_body(doc,
        "甲は、乙に対し末尾記載の車両をリースし、乙はこれを借り受ける。")

    # Article 2
    add_heading_text(doc, "第2条（リース料）")
    add_body(doc, "月額リース料: {{ monthly_lease_fee }}円（消費税別）")
    add_body(doc, "リース期間: {{ lease_term_months }}ヶ月")
    add_body(doc, "リース料総額: {{ total_lease_revenue }}円")
    add_body(doc,
        "乙は、毎月{{ payment_day }}日までに当月分のリース料を甲の指定口座に振り込むものとする。")

    # Article 3
    add_heading_text(doc, "第3条（対象車両）")
    add_body(doc, "メーカー: {{ vehicle_maker }}")
    add_body(doc, "車種: {{ vehicle_model }}")
    add_body(doc, "年式: {{ vehicle_year }}年")
    add_body(doc, "走行距離: {{ vehicle_mileage }}")
    add_body(doc, "車台番号: {{ vehicle_chassis_number }}")
    add_body(doc, "登録番号: {{ vehicle_registration_number }}")

    # Article 4
    add_heading_text(doc, "第4条（使用目的）")
    add_body(doc,
        "乙は、対象車両を営業用車両として使用するものとし、"
        "甲の事前の書面による承諾なく第三者に転貸してはならない。"
        "ただし、第三者へのサブリースについて甲が書面で承諾した場合はこの限りでない。")

    # Article 5
    add_heading_text(doc, "第5条（維持管理）")
    add_body(doc,
        "乙は、善良なる管理者の注意をもって対象車両を使用・保管し、"
        "通常の維持管理費用（点検・整備・保険等）を負担する。")

    # Article 6
    add_heading_text(doc, "第6条（保険）")
    add_body(doc,
        "乙は、リース期間中、対象車両について自動車保険（対人・対物無制限）に加入し、"
        "その証書の写しを甲に提出するものとする。")

    # Article 7
    add_heading_text(doc, "第7条（中途解約）")
    add_body(doc,
        "本契約は、リース期間中の中途解約はできないものとする。"
        "ただし、やむを得ない事由がある場合は、残リース料相当額を違約金として支払うことにより"
        "解約できるものとする。")

    # Article 8
    add_heading_text(doc, "第8条（契約終了時の処理）")
    add_body(doc,
        "リース期間満了時、乙は対象車両を原状に回復のうえ甲に返還するものとする。")

    # Article 9
    add_heading_text(doc, "第9条（管轄裁判所）")
    add_body(doc,
        "本契約に関する紛争については、東京地方裁判所を第一審の専属的合意管轄裁判所とする。")

    add_body(doc,
        "本契約の成立を証するため、本書2通を作成し、甲乙記名押印のうえ各1通を保有する。")

    add_signature_block(doc)

    path = os.path.join(OUTPUT_DIR, "master_lease.docx")
    doc.save(path)
    print(f"Created: {path}")


# ---------------------------------------------------------------------------
# 4. サブリース契約書 (Sublease Agreement)
# ---------------------------------------------------------------------------

def create_sublease_agreement():
    doc = Document()
    set_default_margins(doc)

    add_title(doc, "サブリース契約書")

    add_heading_text(doc, "当事者")
    add_body(doc, "甲（転貸人）: {{ party_a_name }}")
    add_body(doc, "住所: {{ party_a_address }}")
    add_body(doc, "代表者: {{ party_a_representative }}")
    add_blank_line(doc)
    add_body(doc, "乙（転借人）: {{ party_b_name }}")
    add_body(doc, "住所: {{ party_b_address }}")
    add_body(doc, "代表者: {{ party_b_representative }}")
    add_blank_line(doc)
    add_body(doc, "契約日: {{ contract_date }}")

    # Article 1
    add_heading_text(doc, "第1条（サブリースの合意）")
    add_body(doc,
        "甲は、甲がマスターリース契約に基づきリースを受けている末尾記載の車両を、"
        "乙に対しサブリース（転貸）し、乙はこれを借り受ける。")

    # Article 2
    add_heading_text(doc, "第2条（サブリース料）")
    add_body(doc, "月額サブリース料: {{ sublease_fee }}円（消費税別）")
    add_body(doc, "サブリース期間: {{ lease_term_months }}ヶ月")
    add_body(doc,
        "乙は、毎月{{ payment_day }}日までに当月分のサブリース料を甲の指定口座に振り込むものとする。")

    # Article 3
    add_heading_text(doc, "第3条（対象車両）")
    add_body(doc, "メーカー: {{ vehicle_maker }}")
    add_body(doc, "車種: {{ vehicle_model }}")
    add_body(doc, "年式: {{ vehicle_year }}年")
    add_body(doc, "走行距離: {{ vehicle_mileage }}")
    add_body(doc, "車台番号: {{ vehicle_chassis_number }}")
    add_body(doc, "登録番号: {{ vehicle_registration_number }}")

    # Article 4
    add_heading_text(doc, "第4条（使用条件）")
    add_body(doc,
        "乙は、対象車両を事業用車両として使用するものとし、"
        "善良なる管理者の注意をもってこれを使用・保管する。")
    add_body(doc,
        "乙は、甲の事前の書面による承諾なく、対象車両を第三者に再転貸してはならない。")

    # Article 5
    add_heading_text(doc, "第5条（維持管理・保険）")
    add_body(doc,
        "乙は、サブリース期間中の維持管理費用（燃料費、点検・整備費用等）を負担する。")
    add_body(doc,
        "乙は、対象車両について自動車保険（対人・対物無制限）に加入し、"
        "その証書の写しを甲に提出するものとする。")

    # Article 6
    add_heading_text(doc, "第6条（事故・故障時の対応）")
    add_body(doc,
        "乙は、対象車両に事故又は故障が生じた場合、直ちに甲に報告し、"
        "甲の指示に従って対応するものとする。")

    # Article 7
    add_heading_text(doc, "第7条（中途解約）")
    add_body(doc,
        "本契約は、サブリース期間中の中途解約はできないものとする。"
        "ただし、甲乙協議のうえ合意した場合はこの限りでない。")

    # Article 8
    add_heading_text(doc, "第8条（契約終了時の処理）")
    add_body(doc,
        "サブリース期間満了時、乙は対象車両を原状に回復のうえ甲に返還するものとする。")

    # Article 9
    add_heading_text(doc, "第9条（マスターリースとの関係）")
    add_body(doc,
        "本サブリース契約は、甲と車両所有者との間のマスターリース契約に従属する。"
        "マスターリース契約が終了した場合、本契約も当然に終了するものとする。")

    # Article 10
    add_heading_text(doc, "第10条（管轄裁判所）")
    add_body(doc,
        "本契約に関する紛争については、東京地方裁判所を第一審の専属的合意管轄裁判所とする。")

    add_body(doc,
        "本契約の成立を証するため、本書2通を作成し、甲乙記名押印のうえ各1通を保有する。")

    add_signature_block(doc)

    path = os.path.join(OUTPUT_DIR, "sublease_agreement.docx")
    doc.save(path)
    print(f"Created: {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    create_tk_agreement()
    create_sales_agreement()
    create_master_lease()
    create_sublease_agreement()
    print(f"\nAll 4 contract templates created in: {OUTPUT_DIR}")
