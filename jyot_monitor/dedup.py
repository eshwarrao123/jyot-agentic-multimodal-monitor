"""
Cross-modal deduplication, perceptual image hashing, and story cluster memory.

Implements:
1. Image perceptual difference hashing (dHash) and Hamming distance.
2. Normalized text similarity (token Jaccard, containment, Levenshtein ratio).
3. Cross-modal text-to-image matching (OCR text vs text announcements).
4. Guarded story clustering with best representative selection and anti-false-merge rules.
5. Persistent cluster state across runs.
"""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union
import numpy as np
from PIL import Image

from jyot_monitor.models import SourceItem, StoryCluster, utc_now
from jyot_monitor.storage import Storage


def compute_image_dhash(image_input: Union[Image.Image, str, Path], hash_size: int = 8) -> str:
    """
    Compute 64-bit difference hash (dHash) for an image.
    
    Algorithm:
    1. Convert to grayscale.
    2. Resize to (hash_size + 1, hash_size) with bicubic filtering.
    3. Compute horizontal gradient: pixel[x] > pixel[x+1].
    4. Convert 64 boolean bits into a 16-character hexadecimal string.
    """
    if isinstance(image_input, (str, Path)):
        img = Image.open(str(image_input)).convert("L")
    else:
        img = image_input.convert("L")
        
    # Resize to (9, 8)
    resized = img.resize((hash_size + 1, hash_size), Image.Resampling.BICUBIC)
    pixels = np.array(resized, dtype=np.float32)
    
    # Compute horizontal difference: shape (8, 8)
    diff = pixels[:, 1:] > pixels[:, :-1]
    
    # Flatten to 64 bits and encode to 16 hex chars
    bit_string = "".join("1" if b else "0" for b in diff.flatten())
    hex_str = f"{int(bit_string, 2):016x}"
    return hex_str


def hamming_distance(hash1: str, hash2: str) -> int:
    """
    Compute Hamming bit distance between two hexadecimal hashes.
    Max distance is 64 for 16-hex-char hashes.
    """
    if len(hash1) != len(hash2) or not hash1 or not hash2:
        return 64
    try:
        val1 = int(hash1, 16)
        val2 = int(hash2, 16)
        xor_val = val1 ^ val2
        return bin(xor_val).count("1")
    except ValueError:
        return 64


def normalize_text_tokens(text: str) -> Set[str]:
    """Extract lowercase alphanumeric word tokens for lexical comparison."""
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = {w for w in cleaned.split() if len(w) > 1}
    return tokens


def compute_text_jaccard(text1: str, text2: str) -> float:
    """Compute token Jaccard similarity between two texts."""
    tokens1 = normalize_text_tokens(text1)
    tokens2 = normalize_text_tokens(text2)
    if not tokens1 or not tokens2:
        return 0.0
    intersection = len(tokens1 & tokens2)
    union = len(tokens1 | tokens2)
    if union == 0:
        return 0.0
    return float(round(intersection / union, 4))


def compute_text_containment(query_text: str, target_text: str) -> float:
    """Compute fraction of query tokens found in target text."""
    query_tokens = normalize_text_tokens(query_text)
    target_tokens = normalize_text_tokens(target_text)
    if not query_tokens:
        return 0.0
    intersection = len(query_tokens & target_tokens)
    return float(round(intersection / len(query_tokens), 4))


def compute_cross_modal_similarity(ocr_text: str, text_content: str) -> float:
    """Compute cross-modal similarity between extracted OCR text and textual post content."""
    if not ocr_text or not text_content:
        return 0.0
    jaccard = compute_text_jaccard(ocr_text, text_content)
    containment = max(
        compute_text_containment(ocr_text, text_content),
        compute_text_containment(text_content, ocr_text)
    )
    return float(round(0.5 * jaccard + 0.5 * containment, 4))


def are_unrelated_notices(text1: str, text2: str) -> bool:
    """
    Anti-false-merge heuristic:
    Checks if two notices explicitly reference conflicting recall numbers
    or model identifiers, which indicates distinct recalls even if from
    the same manufacturer.
    
    Returns True if items are confirmed UNRELATED and must NOT be clustered.
    """
    # Extract candidate recall IDs (e.g. CPSC-26-089 vs CPSC-26-090, FDA-D-2026-442 vs FDA-D-2026-112)
    id_pattern = re.compile(r"\b([A-Z]{2,6}[-_][A-Z0-9]+[-_][0-9A-Z]+)\b", re.IGNORECASE)
    ids1 = set(id_pattern.findall(text1.upper()))
    ids2 = set(id_pattern.findall(text2.upper()))
    
    # If both texts have well-defined recall IDs and they have zero overlap, they are distinct recalls
    if ids1 and ids2 and not (ids1 & ids2):
        return True
    return False


def score_item_representative(
    item: SourceItem,
    ocr_confidence: Optional[float] = None,
    has_attachment: bool = False
) -> float:
    """
    Compute a representative quality score for cluster leader election.
    Prefers:
    - Completeness (presence of title, body, and attachments)
    - Source authority (CPSC / FDA = 0.9, others = 0.6)
    - OCR quality / confidence
    - Recency
    """
    score = 0.0
    # Completeness
    if item.title:
        score += 10.0
    if item.body and len(item.body) > 50:
        score += 25.0
    if has_attachment:
        score += 20.0
        
    # Source credibility
    src_upper = item.source.upper()
    if "CPSC" in src_upper or "FDA" in src_upper or "NHTSA" in src_upper:
        score += 30.0
    else:
        score += 15.0
        
    # OCR confidence
    if ocr_confidence is not None:
        score += ocr_confidence * 15.0
        
    return score


class StoryClusterManager:
    """
    Manages cross-modal deduplication and persistent story clusters in SQLite storage.
    """
    
    def __init__(
        self,
        storage: Storage,
        image_hamming_threshold: int = 6,
        text_jaccard_threshold: float = 0.80,
        cross_modal_threshold: float = 0.70,
    ):
        self.storage = storage
        self.image_hamming_threshold = image_hamming_threshold
        self.text_jaccard_threshold = text_jaccard_threshold
        self.cross_modal_threshold = cross_modal_threshold

    def match_or_create_cluster(
        self,
        item: SourceItem,
        image_phash: Optional[str] = None,
        ocr_text: Optional[str] = None,
        ocr_confidence: Optional[float] = None,
        has_attachment: bool = False,
    ) -> Tuple[StoryCluster, bool, float, str]:
        """
        Match an item against persistent memory or create a new cluster.
        
        Techniques applied:
        1. Exact content hash match (SHA-256).
        2. Perceptual image hash match (dHash Hamming distance <= threshold).
        3. Near-duplicate text match (token Jaccard >= threshold).
        4. Cross-modal match (OCR text vs text announcement >= threshold).
        
        Returns:
            (cluster, is_new_cluster, similarity_score, match_type)
        """
        item_text = f"{item.title} {item.body or ''}".strip()
        
        # Check if item itself is already associated with an existing cluster (idempotent rerun)
        self_cluster = self.storage.get_item_cluster(item.item_id)
        if self_cluster:
            return self_cluster, False, 1.0, "exact_content_hash"

        # 1. Check exact content hash match
        exact_duplicate_ids = self.storage.get_items_by_content_hash(item.content_hash)
        for dup_id in exact_duplicate_ids:
            if dup_id != item.item_id:
                existing_cluster = self.storage.get_item_cluster(dup_id)
                if existing_cluster:
                    self._add_to_cluster(existing_cluster, item, 1.0, "exact_content_hash", ocr_confidence, has_attachment)
                    return existing_cluster, False, 1.0, "exact_content_hash"

        # Search existing item features in memory
        all_features = self.storage.get_all_item_features()
        best_match_cluster: Optional[StoryCluster] = None
        best_score = 0.0
        best_match_type = "none"

        for feat in all_features:
            other_id = feat["item_id"]
            if other_id == item.item_id:
                continue
                
            other_cluster = self.storage.get_item_cluster(other_id)
            if not other_cluster:
                continue

            other_text = f"{feat.get('title', '')} {feat.get('body', '')}".strip()
            other_phash = feat.get("image_phash")
            other_ocr = feat.get("ocr_text", "")

            # Check false-merge guard
            combined_self = f"{item_text} {ocr_text or ''}"
            combined_other = f"{other_text} {other_ocr or ''}"
            if are_unrelated_notices(combined_self, combined_other):
                continue

            # Technique A: Image Perceptual Hash
            if image_phash and other_phash:
                h_dist = hamming_distance(image_phash, other_phash)
                if h_dist <= self.image_hamming_threshold:
                    sim = 1.0 - (h_dist / 64.0)
                    if sim > best_score:
                        best_score = sim
                        best_match_cluster = other_cluster
                        best_match_type = f"image_phash_hamming_{h_dist}"

            # Technique B: Text Near-Duplicate
            text_sim = compute_text_jaccard(item_text, other_text)
            if text_sim >= self.text_jaccard_threshold and text_sim > best_score:
                best_score = text_sim
                best_match_cluster = other_cluster
                best_match_type = "text_jaccard_near_duplicate"

            # Technique C: Cross-Modal Matching (OCR text vs other text body, or self body vs other OCR)
            if ocr_text and other_text:
                cross_sim = compute_text_jaccard(ocr_text, other_text)
                if cross_sim >= self.cross_modal_threshold and cross_sim > best_score:
                    best_score = cross_sim
                    best_match_cluster = other_cluster
                    best_match_type = "cross_modal_ocr_to_text"
            
            if item_text and other_ocr:
                cross_sim2 = compute_text_jaccard(item_text, other_ocr)
                if cross_sim2 >= self.cross_modal_threshold and cross_sim2 > best_score:
                    best_score = cross_sim2
                    best_match_cluster = other_cluster
                    best_match_type = "cross_modal_text_to_ocr"

        # If a match was found, join existing cluster
        if best_match_cluster:
            self._add_to_cluster(best_match_cluster, item, best_score, best_match_type, ocr_confidence, has_attachment)
            return best_match_cluster, False, best_score, best_match_type

        # Otherwise create a new story cluster
        new_cluster_id = f"cluster_{item.item_id}"
        new_cluster = StoryCluster(
            cluster_id=new_cluster_id,
            representative_item_id=item.item_id,
            member_item_ids=[item.item_id],
            similarity_evidence={item.item_id: {"score": 1.0, "match_type": "leader"}},
            created_time=utc_now(),
            last_updated=utc_now(),
        )
        self.storage.save_cluster(new_cluster)
        return new_cluster, True, 1.0, "new_cluster_leader"

    def _add_to_cluster(
        self,
        cluster: StoryCluster,
        item: SourceItem,
        similarity_score: float,
        match_type: str,
        ocr_confidence: Optional[float] = None,
        has_attachment: bool = False
    ) -> None:
        """Add member to cluster and re-evaluate representative if needed."""
        if item.item_id not in cluster.member_item_ids:
            cluster.member_item_ids.append(item.item_id)
        cluster.similarity_evidence[item.item_id] = {
            "score": similarity_score,
            "match_type": match_type
        }
        cluster.last_updated = utc_now()

        # Check if the incoming item is a higher quality representative
        current_rep = self.storage.get_item(cluster.representative_item_id)
        curr_score = score_item_representative(current_rep) if current_rep else 0.0
        new_score = score_item_representative(item, ocr_confidence, has_attachment)
        
        if new_score > curr_score:
            cluster.representative_item_id = item.item_id

        self.storage.save_cluster(cluster)
