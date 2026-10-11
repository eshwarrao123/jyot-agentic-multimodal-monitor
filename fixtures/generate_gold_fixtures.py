"""
Generation script for controlled OCR evaluation gold fixtures.

NOTE: These fixtures are synthetic / controlled test fixtures generated locally
for reproducible offline OCR evaluation and preprocessing ablation.
Performance on synthetic fixtures does not represent all real-world scanned documents.

Ground-truth transcriptions are explicitly human-authored and verified before rendering,
and are never copied from OCR predictions.
"""

import io
import json
import math
import os
from pathlib import Path
import random
from typing import Any, Dict, List
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
import pymupdf


FIXTURES_DIR = Path(__file__).resolve().parent / "gold"
IMAGES_DIR = FIXTURES_DIR / "images"
PDFS_DIR = FIXTURES_DIR / "pdfs"

# Windows fonts
INDIC_FONT_PATH = r"C:\Windows\Fonts\Nirmala.ttc"
SANS_FONT_PATH = r"C:\Windows\Fonts\arial.ttf"


def get_font(size: int = 24, indic: bool = False) -> ImageFont.ImageFont:
    """Get TTF font or fallback to default."""
    if indic and os.path.isfile(INDIC_FONT_PATH):
        try:
            return ImageFont.truetype(INDIC_FONT_PATH, size)
        except Exception:
            pass
    if os.path.isfile(SANS_FONT_PATH):
        try:
            return ImageFont.truetype(SANS_FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


def render_text_to_image(
    lines: List[str],
    font_size: int = 24,
    width: int = 800,
    padding: int = 30,
    indic: bool = False,
    bg_color: tuple = (255, 255, 255),
    text_color: tuple = (0, 0, 0),
) -> Image.Image:
    """Render lines of text cleanly onto a canvas."""
    font = get_font(font_size, indic=indic)
    line_height = int(font_size * 1.6)
    height = max(150, padding * 2 + len(lines) * line_height)
    
    img = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(img)
    
    y = padding
    for line in lines:
        draw.text((padding, y), line, font=font, fill=text_color)
        y += line_height
        
    return img


def apply_gaussian_noise(image: Image.Image, mean: float = 0, sigma: float = 35) -> Image.Image:
    """Add Gaussian noise to simulate poor scanning or sensor grain."""
    np_img = np.array(image).astype(np.float32)
    noise = np.random.normal(mean, sigma, np_img.shape)
    noisy_img = np.clip(np_img + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(noisy_img)


def apply_low_contrast(image: Image.Image) -> Image.Image:
    """Compress intensity range towards gray (140-180) to simulate washed out print."""
    np_img = np.array(image).astype(np.float32)
    compressed = 140.0 + (np_img / 255.0) * 45.0
    return Image.fromarray(np.clip(compressed, 0, 255).astype(np.uint8))


def apply_blur(image: Image.Image, radius: int = 2) -> Image.Image:
    """Apply Gaussian blur to simulate defocus or camera shake."""
    return image.filter(ImageFilter.GaussianBlur(radius=radius))


def apply_rotation(image: Image.Image, angle: float) -> Image.Image:
    """Rotate image by angle degrees with white background fill."""
    return image.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(255, 255, 255))


# 18 Labelled Ground Truth Fixtures
DATASET_SPECS = [
    # 1-6: Clean English notices and screenshots
    {
        "id": "rec_en_clean_01",
        "category": "clean_english",
        "difficulty": "easy",
        "language": "en",
        "degradation": "none",
        "document_type": "notice",
        "lines": [
            "CONSUMER PRODUCT SAFETY COMMISSION RECALL NOTICE",
            "Product Name: Infant Sleeper Deluxe Bassinet",
            "Manufacturer: BabyCare Global Industries Ltd.",
            "Recall Date: 2026-03-15",
            "Hazard: Suffocation and entrapment risk due to loose side railings.",
            "Remedy: Immediately stop using the bassinet and contact manufacturer for refund.",
            "Recall Number: CPSC-26-089 Units: 45,000",
        ],
    },
    {
        "id": "rec_en_clean_02",
        "category": "clean_english",
        "difficulty": "easy",
        "language": "en",
        "degradation": "none",
        "document_type": "notice",
        "lines": [
            "FOOD AND DRUG ADMINISTRATION URGENT ALERT",
            "Product Name: Metformin Hydrochloride Extended-Release 500mg",
            "Manufacturer: Apex Pharma Laboratories Inc.",
            "Notice Date: 2026-04-10",
            "Hazard: Detection of NDMA impurity above acceptable daily intake limit.",
            "Recommended Action: Return affected lots to pharmacy for replacement.",
            "Recall Number: FDA-D-2026-442",
        ],
    },
    {
        "id": "rec_en_clean_03",
        "category": "clean_english",
        "difficulty": "easy",
        "language": "en",
        "degradation": "none",
        "document_type": "screenshot",
        "lines": [
            "SAFETY WARNING: BICYCLE BRAKE CABLE FAILURE",
            "Brand: Apex TrailMaster Mountain Bikes",
            "Date: 2026-05-02",
            "Hazard: Front brake cable detachment can cause crash and serious injury.",
            "Consumer Action: Stop riding immediately and schedule free repair.",
            "Campaign ID: BIKE-26-901",
        ],
    },
    {
        "id": "rec_en_clean_04",
        "category": "clean_english",
        "difficulty": "easy",
        "language": "en",
        "degradation": "none",
        "document_type": "notice",
        "lines": [
            "NATIONAL HIGHWAY TRAFFIC SAFETY DEFECT NOTICE",
            "Product Name: Wireless Tire Pressure Monitoring Sensor",
            "Manufacturer: SafeDrive Auto Components",
            "Recall Date: 2026-06-18",
            "Hazard: Inaccurate pressure readings may lead to undetected tire blowout.",
            "Action: Authorized dealers will inspect and replace sensor module free of charge.",
            "Recall ID: NHTSA-26V-112",
        ],
    },
    {
        "id": "rec_en_clean_05",
        "category": "clean_english",
        "difficulty": "easy",
        "language": "en",
        "degradation": "none",
        "document_type": "screenshot",
        "lines": [
            "FDA PUBLIC HEALTH ADVISORY: SALMONELLA CONTAMINATION",
            "Product: Organic Crunchy Peanut Butter 16oz",
            "Distributed by: NutriHarvest Brands",
            "Recall Date: 2026-07-22",
            "Risk: Potential contamination with Salmonella bacteria causing severe illness.",
            "Remedy: Do not consume product. Return to store of purchase for full refund.",
            "Lot Codes: Lot 2605-B and Lot 2606-A",
        ],
    },
    {
        "id": "rec_en_clean_06",
        "category": "clean_english",
        "difficulty": "easy",
        "language": "en",
        "degradation": "none",
        "document_type": "notice",
        "lines": [
            "PRODUCT SAFETY RECALL: CERAMIC SPACE HEATER",
            "Product Name: WarmHome 1500W Oscillating Space Heater",
            "Manufacturer: WarmHome Electric Appliances",
            "Date: 2026-08-30",
            "Hazard: Internal heating element can overheat and ignite casing, posing fire hazard.",
            "Recommended Action: Unplug heater immediately and register for replacement kit.",
            "Recall Identifier: HEATER-26-440 Units: 120,000",
        ],
    },

    # 7-11: Difficult cases (rotation, blur, low contrast, noise)
    {
        "id": "rec_en_diff_rot15",
        "category": "difficult_english",
        "difficulty": "hard",
        "language": "en",
        "degradation": "rotation_15",
        "document_type": "notice",
        "lines": [
            "SAFETY RECALL NOTICE: 2-SLICE ELECTRIC TOASTER",
            "Product: QuickToast Deluxe Smart Toaster",
            "Manufacturer: CulinaryTech Devices Inc.",
            "Date: 2026-09-12",
            "Hazard: Heating coils can remain energized after pop-up cycle.",
            "Remedy: Disconnect from power outlet and request repair box.",
            "Recall ID: CPSC-TOAST-26",
        ],
    },
    {
        "id": "rec_en_diff_rot_neg20",
        "category": "difficult_english",
        "difficulty": "hard",
        "language": "en",
        "degradation": "rotation_neg20",
        "document_type": "notice",
        "lines": [
            "BATTERY PACK OVERHEATING RECALL",
            "Product Name: Lithium-Ion 20V Max Power Drill Battery",
            "Manufacturer: PowerCraft Tool Corporation",
            "Recall Date: 2026-09-25",
            "Hazard: Battery cells can short circuit during charging, creating fire risk.",
            "Consumer Action: Stop charging battery and recycle at authorized drop-off depot.",
            "Recall Number: BATT-26-880",
        ],
    },
    {
        "id": "rec_en_diff_blur",
        "category": "difficult_english",
        "difficulty": "hard",
        "language": "en",
        "degradation": "blur",
        "document_type": "notice",
        "lines": [
            "BURN HAZARD WARNING: CHILDREN SLEEPWEAR",
            "Product Name: CozyKids Fleece Pajama Sets",
            "Manufacturer: Global Apparel Solutions",
            "Notice Date: 2026-10-01",
            "Hazard: Sleepwear fails to meet federal flammability standards.",
            "Remedy: Keep away from fire and return for full purchase price refund.",
            "Recall Number: CPSC-26-940",
        ],
    },
    {
        "id": "rec_en_diff_lowcontrast",
        "category": "difficult_english",
        "difficulty": "hard",
        "language": "en",
        "degradation": "low_contrast",
        "document_type": "notice",
        "lines": [
            "CRITICAL ALERT: RESIDENTIAL SMOKE DETECTOR",
            "Product Name: SafeGuard Dual-Sensor Smoke Alarm",
            "Manufacturer: SafeGuard Home Security Inc.",
            "Recall Date: 2026-10-05",
            "Hazard: Battery contact corrosion may silence alarm during active smoke event.",
            "Action: Contact SafeGuard customer service for expedited sensor replacement.",
            "Model Number: SG-SMOKE-2026",
        ],
    },
    {
        "id": "rec_en_diff_noise",
        "category": "difficult_english",
        "difficulty": "hard",
        "language": "en",
        "degradation": "noise",
        "document_type": "notice",
        "lines": [
            "MEDICAL EQUIPMENT SAFETY ALERT: INFUSION PUMP",
            "Product: MediFlow Automated Infusion Pump System",
            "Manufacturer: MediTech Health Systems",
            "Date: 2026-10-08",
            "Hazard: Software defect causes inaccurate fluid delivery rates.",
            "Remedy: Hospital biomedical engineers must apply firmware patch v3.2.",
            "Recall Campaign: MED-26-707",
        ],
    },

    # 12-15: Hindi samples with verified human ground truth
    {
        "id": "rec_hi_clean_01",
        "category": "hindi",
        "difficulty": "easy",
        "language": "hi",
        "degradation": "none",
        "document_type": "notice",
        "lines": [
            "खाद्य सुरक्षा एवं मानक प्राधिकरण जन सूचना",
            "उत्पाद: शुद्ध मसाला पावडर ५०० ग्राम",
            "निर्माता: भारत स्पाइस उद्योग प्राइवेट लिमिटेड",
            "दिनांक: 2026-05-15",
            "खतरा: स्वास्थ्य के लिए हानिकारक मिलावट की पुष्टि।",
            "कार्रवाई: उपभोक्ता तुरंत उपयोग बंद करें और धनवापसी प्राप्त करें।",
            "रिकॉल क्रमांक: FSSAI-26-102",
        ],
    },
    {
        "id": "rec_hi_clean_02",
        "category": "hindi",
        "difficulty": "medium",
        "language": "hi",
        "degradation": "none",
        "document_type": "notice",
        "lines": [
            "खिलौना सुरक्षा चेतावनी सूचना",
            "उत्पाद: बच्चों की इलेक्ट्रॉनिक कार टॉय",
            "ब्रांड: बाल आनंद टॉयज कॉर्पोरेशन",
            "दिनांक: 2026-06-20",
            "खतरा: छोटे पुर्जों के टूटने से बच्चों के लिए दम घुटने का गंभीर जोखिम।",
            "सुझाव: बच्चों से खिलौना तुरंत दूर रखें और निकटतम केंद्र पर लौटाएं।",
            "सुरक्षा कोड: TOY-HI-26",
        ],
    },
    {
        "id": "rec_hi_clean_03",
        "category": "hindi",
        "difficulty": "medium",
        "language": "hi",
        "degradation": "none",
        "document_type": "notice",
        "lines": [
            "अग्नि सुरक्षा रिकॉल बुलेटिन",
            "उत्पाद का नाम: घरेलू रूम हीटर 2000 वॉट",
            "निर्माता: सूर्य इलेक्ट्रिकल्स लिमिटेड",
            "सूचना दिनांक: 2026-07-11",
            "खतरा: अत्यधिक गर्म होने पर आग लगने और जलने का खतरा।",
            "उपभोक्ता निर्देश: बिजली का प्लग निकालें और निशुल्क मरम्मत कराएं।",
            "रिकॉल पहचान: SURYA-26-09",
        ],
    },
    {
        "id": "rec_hi_clean_04",
        "category": "hindi",
        "difficulty": "hard",
        "language": "hi",
        "degradation": "noise",
        "document_type": "notice",
        "lines": [
            "वाहन सुरक्षा एवं गुणवत्ता चेतावनी",
            "वाहन मॉडल: गति ऑटो स्कूटर 125cc",
            "कंपनी: गति मोटर्स इंडिया लिमिटेड",
            "रिकॉल तिथि: 2026-08-04",
            "खराबी: फ्रंट डिस्क ब्रेक के लॉक होने से दुर्घटना का अंदेशा।",
            "कदम: अधिकृत डीलर से संपर्क कर ब्रेक कैलीपर निःशुल्क बदलवाएं।",
            "अभियान संख्या: GATI-26-MOTO",
        ],
    },

    # 16-18: Multi-page scanned PDF (3 pages)
    {
        "id": "rec_pdf_page_01",
        "category": "scanned_pdf",
        "difficulty": "easy",
        "language": "en",
        "degradation": "none",
        "document_type": "scanned_page",
        "lines": [
            "OFFICIAL RECALL BULLETIN - PAGE 1 OF 3",
            "UNITED STATES CONSUMER PRODUCT SAFETY COMMISSION",
            "General Notice for Portable Camping Stoves",
            "Summary: Joint voluntary recall of outdoor butane camping stoves.",
            "Issued: October 2026",
            "Reference Document: CPSC-PDF-BULLETIN-2026",
        ],
    },
    {
        "id": "rec_pdf_page_02",
        "category": "scanned_pdf",
        "difficulty": "medium",
        "language": "en",
        "degradation": "none",
        "document_type": "scanned_page",
        "lines": [
            "OFFICIAL RECALL BULLETIN - PAGE 2 OF 3",
            "IDENTIFICATION AND HAZARD SPECIFICATIONS",
            "Product: CampPro Portable Butane Stove Model CP-2026",
            "Hazard Description: Gas valve seal failure allows butane leakage causing flash fire.",
            "Units Affected: Approximately 38,000 units sold nationwide.",
            "Serial Number Range: CP26-0001 through CP26-3800",
        ],
    },
    {
        "id": "rec_pdf_page_03",
        "category": "scanned_pdf",
        "difficulty": "easy",
        "language": "en",
        "degradation": "none",
        "document_type": "scanned_page",
        "lines": [
            "OFFICIAL RECALL BULLETIN - PAGE 3 OF 3",
            "REMEDY AND CONSUMER CONTACT INFORMATION",
            "Remedy: Consumers should immediately cease using recalled stoves.",
            "Contact: CampPro Safety Hotline at 1-800-555-0199 Monday through Friday.",
            "Refund or replacement valve assembly provided free of charge.",
            "Bulletin Authorized by Office of Product Safety.",
        ],
    },
]


def generate_all_fixtures() -> Dict[str, Any]:
    """Render all fixture images, multi-page PDF, and gold manifest."""
    random.seed(42)
    np.random.seed(42)

    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    PDFS_DIR.mkdir(parents=True, exist_ok=True)

    manifest_records = []
    pdf_page_images = []

    for spec in DATASET_SPECS:
        rec_id = spec["id"]
        is_indic = spec["language"] == "hi"
        base_img = render_text_to_image(
            spec["lines"],
            font_size=24 if not is_indic else 26,
            indic=is_indic,
        )

        deg = spec["degradation"]
        if deg == "rotation_15":
            final_img = apply_rotation(base_img, 15.0)
        elif deg == "rotation_neg20":
            final_img = apply_rotation(base_img, -20.0)
        elif deg == "blur":
            final_img = apply_blur(base_img, radius=2)
        elif deg == "low_contrast":
            final_img = apply_low_contrast(base_img)
        elif deg == "noise":
            final_img = apply_gaussian_noise(base_img, sigma=25)
        else:
            final_img = base_img

        # Ground truth is joined text of all lines
        ground_truth = " ".join(spec["lines"])

        if spec["category"] == "scanned_pdf":
            # Collect for PDF creation
            pdf_page_images.append((rec_id, final_img, spec, ground_truth))
        else:
            # Save standalone image
            img_filename = f"{rec_id}.png"
            img_path = IMAGES_DIR / img_filename
            final_img.save(img_path, format="PNG")

            manifest_records.append({
                "record_id": rec_id,
                "file_path": f"images/{img_filename}",
                "page_number": None,
                "language": spec["language"],
                "difficulty": spec["difficulty"],
                "category": spec["category"],
                "degradation": deg,
                "document_type": spec["document_type"],
                "ground_truth_text": ground_truth,
                "is_synthetic": True,
            })

    # Create 3-page scanned PDF
    pdf_filename = "sample_recall_notice_scanned.pdf"
    pdf_path = PDFS_DIR / pdf_filename

    doc = pymupdf.open()
    for page_idx, (rec_id, page_img, spec, ground_truth) in enumerate(pdf_page_images):
        # Save page as temporary image buffer
        buf = io.BytesIO()
        page_img.save(buf, format="PNG")
        buf.seek(0)

        # Insert page into PDF with image rect
        page = doc.new_page(width=page_img.width, height=page_img.height)
        page.insert_image(page.rect, stream=buf.getvalue())

        manifest_records.append({
            "record_id": rec_id,
            "file_path": f"pdfs/{pdf_filename}",
            "page_number": page_idx + 1,
            "language": spec["language"],
            "difficulty": spec["difficulty"],
            "category": spec["category"],
            "degradation": spec["degradation"],
            "document_type": spec["document_type"],
            "ground_truth_text": ground_truth,
            "is_synthetic": True,
        })

    doc.save(str(pdf_path))
    doc.close()

    manifest_data = {
        "dataset_name": "jyot_ocr_gold_v1",
        "description": "Synthetic controlled evaluation fixtures for multi-engine OCR and preprocessing ablation.",
        "version": "1.0.0",
        "total_records": len(manifest_records),
        "language_distribution": {
            "en": sum(1 for r in manifest_records if r["language"] == "en"),
            "hi": sum(1 for r in manifest_records if r["language"] == "hi"),
        },
        "difficulty_distribution": {
            "easy": sum(1 for r in manifest_records if r["difficulty"] == "easy"),
            "medium": sum(1 for r in manifest_records if r["difficulty"] == "medium"),
            "hard": sum(1 for r in manifest_records if r["difficulty"] == "hard"),
        },
        "records": manifest_records,
    }

    manifest_path = FIXTURES_DIR / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    print(f"Generated {len(manifest_records)} gold fixtures in {FIXTURES_DIR}")
    return manifest_data


if __name__ == "__main__":
    generate_all_fixtures()
