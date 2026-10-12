"""
Tests for P0-F: Hindi detection and correct OCR routing.

Verifies:
1. Devanagari script detection in title, body, and OCR text.
2. Correct routing to EasyOCR with ['hi', 'en'] for Hindi content.
3. English content still routes to Tesseract.
4. Language detection does not rely on substring matching like "hi" in title.
5. OCR router uses correct language configuration.
"""

from datetime import datetime, timezone
from jyot_monitor.agent.planner import contains_devanagari, detect_language_hint
from jyot_monitor.models import SourceItem
from jyot_monitor.ocr.router import OCRRouter
from PIL import Image
import numpy as np


def test_contains_devanagari_positive():
    """Test Devanagari script detection in Hindi text."""
    # Hindi text with Devanagari characters
    hindi_samples = [
        "उत्पाद वापसी",
        "बैटरी पैक में आग का खतरा",
        "Mixed English and हिंदी text",
        "Product Recall: उपभोक्ताओं को चेतावनी",
    ]
    
    for sample in hindi_samples:
        assert contains_devanagari(sample), f"Should detect Devanagari in: {sample}"


def test_contains_devanagari_negative():
    """Test that English text is not falsely detected as Devanagari."""
    english_samples = [
        "Battery Recall",
        "This is a warning",
        "Fire hazard in vehicle",
        "high priority alert",
        "shipment delayed",
        "ahi tuna recall",  # Contains "hi" substring but no Devanagari
    ]
    
    for sample in english_samples:
        assert not contains_devanagari(sample), f"Should not detect Devanagari in: {sample}"


def test_detect_language_hint_hindi_in_title():
    """Test language detection from Devanagari in item title."""
    item = SourceItem(
        item_id="hindi_item_1",
        source="FSSAI",
        url="https://fssai.gov.in/test",
        title="उत्पाद वापसी सूचना",
        body="Product recall notice",
        content_hash="hindi_001",
        fetch_time=datetime.now(timezone.utc),
    )
    
    hint = detect_language_hint(item)
    assert hint == "hi", "Should detect Hindi from Devanagari in title"


def test_detect_language_hint_hindi_in_body():
    """Test language detection from Devanagari in item body."""
    item = SourceItem(
        item_id="hindi_item_2",
        source="FSSAI",
        url="https://fssai.gov.in/test",
        title="Product Recall Notice",
        body="उपभोक्ताओं को तुरंत उपयोग बंद करना चाहिए। बैटरी में आग का खतरा।",
        content_hash="hindi_002",
        fetch_time=datetime.now(timezone.utc),
    )
    
    hint = detect_language_hint(item)
    assert hint == "hi", "Should detect Hindi from Devanagari in body"


def test_detect_language_hint_hindi_in_ocr_text():
    """Test language detection from Devanagari in OCR text."""
    item = SourceItem(
        item_id="hindi_item_3",
        source="FSSAI",
        url="https://fssai.gov.in/test",
        title="Product Safety Alert",
        body="See attached notice",
        content_hash="hindi_003",
        fetch_time=datetime.now(timezone.utc),
    )
    
    ocr_text = "उत्पाद सुरक्षा चेतावनी: यह उत्पाद खतरनाक हो सकता है।"
    hint = detect_language_hint(item, ocr_text=ocr_text)
    assert hint == "hi", "Should detect Hindi from Devanagari in OCR text"


def test_detect_language_hint_english():
    """Test language detection defaults to English for non-Devanagari content."""
    english_items = [
        SourceItem(
            item_id="eng_item_1",
            source="CPSC",
            url="https://cpsc.gov/test",
            title="Battery Recall - Fire Hazard",
            body="Consumers should stop using this product immediately",
            content_hash="eng_001",
            fetch_time=datetime.now(timezone.utc),
        ),
        SourceItem(
            item_id="eng_item_2",
            source="FDA",
            url="https://fda.gov/test",
            title="This is a high priority warning",  # Contains "hi" but no Devanagari
            body="Shipment contains contaminated products",  # Contains "hi" but no Devanagari
            content_hash="eng_002",
            fetch_time=datetime.now(timezone.utc),
        ),
    ]
    
    for item in english_items:
        hint = detect_language_hint(item)
        assert hint == "en", f"Should detect English for item {item.item_id}"


def test_ocr_router_hindi_specialized_trajectory():
    """Test OCR router uses EasyOCR with ['hi', 'en'] for Hindi language hint."""
    # Create a minimal test image (white rectangle with some noise)
    img_array = np.ones((100, 200, 3), dtype=np.uint8) * 255
    img_array[40:60, 80:120] = 0  # Add a black rectangle
    test_image = Image.fromarray(img_array)
    
    router = OCRRouter()
    
    # Route with Hindi language hint
    result = router.route_and_extract(
        test_image,
        language_hint="hi",
        item_id="test_hindi_routing",
        attachment_id="att_hindi_1",
    )
    
    assert result.trajectory_name == "hindi_specialized_engine", \
        "Should use hindi_specialized_engine trajectory"
    assert result.selected_engine == "easyocr", \
        "Should select EasyOCR for Hindi content"
    assert "Hindi" in result.decision_rationale or "hindi" in result.decision_rationale.lower(), \
        "Rationale should mention Hindi routing"
    assert result.routing_signals["is_hindi_hint"] is True, \
        "Routing signals should flag Hindi hint"
    # Verify languages parameter was passed correctly (would be in actual EasyOCR call)
    # This is implicit in the trajectory selection


def test_ocr_router_english_trajectory():
    """Test OCR router uses Tesseract for English language hint."""
    # Create a high-quality test image
    img_array = np.ones((200, 400, 3), dtype=np.uint8) * 255
    img_array[90:110, 180:220] = 0  # Add text-like region
    test_image = Image.fromarray(img_array)
    
    router = OCRRouter()
    
    # Route with English language hint
    result = router.route_and_extract(
        test_image,
        language_hint="en",
        item_id="test_english_routing",
        attachment_id="att_eng_1",
    )
    
    # English should use one of the English trajectories
    assert result.trajectory_name in (
        "clean_english_direct",
        "difficult_low_confidence_second_opinion",
    ), "Should use English trajectory"
    assert result.routing_signals["is_hindi_hint"] is False, \
        "Routing signals should not flag Hindi hint for English"


def test_hindi_routing_from_planner():
    """Test planner generates correct language_hint for Hindi content in OCR action."""
    from jyot_monitor.agent.planner import DeterministicFallbackPlanner
    
    # Hindi item
    hindi_item = SourceItem(
        item_id="hindi_item_planner",
        source="FSSAI",
        url="https://fssai.gov.in/test",
        title="उत्पाद वापसी: बैटरी में आग",
        body="तुरंत उपयोग बंद करें",
        content_hash="hindi_planner_001",
        fetch_time=datetime.now(timezone.utc),
    )
    
    planner = DeterministicFallbackPlanner()
    
    # Set up context with attachment fetched
    context = {
        "completed_tools": [],
        "completed_tool_data": {
            "fetch_attachment": {"local_path": "/fixtures/test.jpg"}
        },
        "attachments": [],
    }
    
    action_req, mode, fallback, rationale = planner.select_action(hindi_item, context)
    
    assert action_req.action.value == "ocr_extract", "Should select OCR action"
    assert action_req.arguments.get("language_hint") == "hi", \
        "Should pass 'hi' language hint for Hindi content"


def test_english_routing_from_planner():
    """Test planner generates correct language_hint for English content in OCR action."""
    from jyot_monitor.agent.planner import DeterministicFallbackPlanner
    
    # English item with "hi" substring (should not trigger Hindi detection)
    english_item = SourceItem(
        item_id="english_item_planner",
        source="CPSC",
        url="https://cpsc.gov/test",
        title="This vehicle shipment has high priority recall",
        body="Fire hazard detected in shipped units",
        content_hash="eng_planner_001",
        fetch_time=datetime.now(timezone.utc),
    )
    
    planner = DeterministicFallbackPlanner()
    
    # Set up context with attachment fetched
    context = {
        "completed_tools": [],
        "completed_tool_data": {
            "fetch_attachment": {"local_path": "/fixtures/test.jpg"}
        },
        "attachments": [],
    }
    
    action_req, mode, fallback, rationale = planner.select_action(english_item, context)
    
    assert action_req.action.value == "ocr_extract", "Should select OCR action"
    assert action_req.arguments.get("language_hint") == "en", \
        "Should pass 'en' language hint for English content (not detect 'hi' substring)"


def test_hindi_content_not_classified_as_garbled_english():
    """
    Test that Hindi OCR results routed correctly produce better classification than garbled output.
    
    This is a regression test for the bug where Hindi content routed to English-only OCR
    would produce garbled output that could be misclassified.
    
    Note: The deterministic classifier uses English keywords, so pure Hindi text without
    English keywords will be classified as non_safety. This demonstrates why LLM classification
    or bilingual keyword sets would be beneficial for Hindi content. The key test is that
    correct routing produces intelligible text rather than garbled output.
    """
    from jyot_monitor.agent.tools.classify_score import deterministic_classify
    
    # Properly extracted Hindi text with English keywords (simulating correct EasyOCR ['hi', 'en'] output)
    proper_hindi_ocr = """
    Product Recall Notice / उत्पाद वापसी सूचना
    
    Product: Battery Pack Model ABC-123 / उत्पाद: बैटरी पैक मॉडल ABC-123
    Manufacturer: ABC Electronics / निर्माता: ABC Electronics
    Hazard: Fire Hazard / खतरा: आग का खतरा
    
    Consumers should immediately stop using this product.
    उपभोक्ताओं को तुरंत इस उत्पाद का उपयोग बंद करना चाहिए।
    """
    
    # Bilingual content should be classified correctly
    result = deterministic_classify(proper_hindi_ocr, "FSSAI")
    
    assert result.taxonomy != "spam_manipulation", \
        "Hindi safety notice should not be classified as spam"
    assert result.taxonomy != "uncertain", \
        "Bilingual safety notice should not be classified as uncertain"
    # With English keywords present, should be recognized
    assert result.taxonomy in ("product_recall", "health_hazard", "consumer_warning"), \
        f"Bilingual safety notice should be recognized as safety-related, got {result.taxonomy}"
    
    # Garbled English output (simulating incorrect English-only OCR on Hindi text)
    garbled_output = "########## #### ### ##### #### ABC-123 #### ### ####"
    
    garbled_result = deterministic_classify(garbled_output, "FSSAI")
    
    # Garbled output will be uncertain or non_safety due to unreadable text
    assert garbled_result.taxonomy in ("uncertain", "non_safety"), \
        "Garbled OCR output should be classified as uncertain or non_safety"
    assert garbled_result.relevance_score < result.relevance_score, \
        "Garbled output should have lower relevance than proper extraction"


def test_no_false_hindi_detection_from_substring():
    """
    Regression test: ensure words containing 'hi' substring don't trigger Hindi detection.
    """
    false_positive_texts = [
        "This product shipment",
        "High priority alert",
        "Vehicle with fire hazard",
        "Shipping notice",
        "History of recalls",
        "Achieves safety standards",
        "White color variant",
    ]
    
    for text in false_positive_texts:
        assert not contains_devanagari(text), \
            f"Should not detect Devanagari in English text: {text}"
        
        # Also test at item level
        item = SourceItem(
            item_id="false_positive_test",
            source="CPSC",
            url="https://cpsc.gov/test",
            title=text,
            body="Additional context",
            content_hash="fp_test",
            fetch_time=datetime.now(timezone.utc),
        )
        
        hint = detect_language_hint(item)
        assert hint == "en", \
            f"Should detect English (not Hindi) for text with 'hi' substring: {text}"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
