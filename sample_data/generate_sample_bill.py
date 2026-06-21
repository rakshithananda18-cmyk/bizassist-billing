import os
from PIL import Image, ImageDraw, ImageFont

def generate_invoice_image():
    # Create a white canvas (A4 aspect ratio approximately)
    width, height = 800, 1000
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    # Resolve fonts (Windows system fonts preferred, fallback to default)
    try:
        font_title = ImageFont.truetype("arialbd.ttf", 28)
        font_header = ImageFont.truetype("arialbd.ttf", 16)
        font_regular = ImageFont.truetype("arial.ttf", 13)
        font_bold = ImageFont.truetype("arialbd.ttf", 13)
    except IOError:
        # Fallback for systems without Arial
        font_title = ImageFont.load_default()
        font_header = font_title
        font_regular = font_title
        font_bold = font_title

    # Draw header section
    draw.text((40, 40), "TAX INVOICE", fill="black", font=font_title)
    
    draw.text((40, 90), "Apex Pharma Distributors", fill="black", font=font_header)
    draw.text((40, 110), "12, Industrial Area, Bangalore - 560001", fill="gray", font=font_regular)
    draw.text((40, 125), "GSTIN: 29APEXPD1234F1Z5 | Phone: +91 98765 43210", fill="gray", font=font_regular)

    # Draw Invoice metadata
    draw.text((500, 90), "Invoice No: APEX-2026-908", fill="black", font=font_bold)
    draw.text((500, 110), "Date: 2026-06-15", fill="black", font=font_regular)
    draw.text((500, 125), "Due Date: 2026-07-15", fill="black", font=font_regular)

    # Draw Divider
    draw.line((40, 160, 760, 160), fill="lightgray", width=1)

    # Draw Bill To section
    draw.text((40, 180), "BILLED TO:", fill="gray", font=font_header)
    draw.text((40, 200), "MediCare Pharmacy", fill="black", font=font_bold)
    draw.text((40, 215), "5th Block, Koramangala, Bangalore - 560034", fill="black", font=font_regular)
    draw.text((40, 230), "GSTIN: 29MEDICARE1234A1Z0", fill="black", font=font_regular)

    # Draw Divider
    draw.line((40, 260, 760, 260), fill="black", width=2)

    # Table headers
    headers = [
        ("Item Description", 40),
        ("HSN", 250),
        ("Qty", 320),
        ("Unit", 380),
        ("Rate", 440),
        ("Taxable Val", 510),
        ("GST %", 610),
        ("Total (INR)", 680)
    ]
    
    for h, x in headers:
        draw.text((x, 275), h, fill="black", font=font_bold)

    draw.line((40, 300, 760, 300), fill="black", width=2)

    # Table rows
    rows = [
        ("Paracetamol 650mg", "3004", "10", "Box", "100.00", "1000.00", "12%", "1120.00"),
        ("Amoxicillin 500mg", "3004", "5", "Box", "200.00", "1000.00", "12%", "1120.00"),
        ("Dolo 650", "3004", "20", "Nos", "15.00", "300.00", "12%", "336.00")
    ]

    y_pos = 320
    for row in rows:
        draw.text((40, y_pos), row[0], fill="black", font=font_regular)
        draw.text((250, y_pos), row[1], fill="black", font=font_regular)
        draw.text((320, y_pos), row[2], fill="black", font=font_regular)
        draw.text((380, y_pos), row[3], fill="black", font=font_regular)
        draw.text((440, y_pos), row[4], fill="black", font=font_regular)
        draw.text((510, y_pos), row[5], fill="black", font=font_regular)
        draw.text((610, y_pos), row[6], fill="black", font=font_regular)
        draw.text((680, y_pos), row[7], fill="black", font=font_bold)
        
        y_pos += 30
        draw.line((40, y_pos - 10, 760, y_pos - 10), fill="lightgray", width=1)

    # Totals Section
    draw.line((40, y_pos + 10, 760, y_pos + 10), fill="black", width=2)
    
    totals = [
        ("Subtotal:", "2,300.00", y_pos + 30),
        ("CGST (6%):", "138.00", y_pos + 50),
        ("SGST (6%):", "138.00", y_pos + 70),
        ("Grand Total:", "2,576.00", y_pos + 100)
    ]

    for label, val, y in totals:
        is_grand = "Grand" in label
        f_lbl = font_bold if is_grand else font_regular
        f_val = font_header if is_grand else font_regular
        color = "black"
        
        draw.text((500, y), label, fill=color, font=f_lbl)
        draw.text((680, y), val, fill=color, font=f_val)

    # Save to file
    out_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(out_dir, "sample_bill.png")
    img.save(out_path)
    print(f"Successfully generated sample bill at: {out_path}")

if __name__ == "__main__":
    generate_invoice_image()
