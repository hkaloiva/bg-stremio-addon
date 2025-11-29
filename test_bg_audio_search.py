#!/usr/bin/env python3
"""
Test script to search for Bulgarian audio in stream names.
Analyzes how many streams would be detected by the audio detection feature.
"""
import re
import json

# Sample stream names from various sources (torrent releases, etc.)
test_streams = [
    # Positive cases - should detect BG audio
    "Movie.2024.BG.Audio.1080p.WEB-DL.x264",
    "Series.S01E01.BGAudio.720p.BluRay",
    "Film.2023.BG-Audio.2160p.HDR",
    "Movie.BG.Dub.1080p",
    "Film.2024.Bulgarian.Audio.WEB-DL",
    "Movie.2023.БГ.Аудио.1080p",
    "Series.БГ.Дублаж.720p",
    
    # Negative cases - should NOT detect
    "Movie.2024.1080p.WEB-DL.x264",
    "Series.S01E01.720p.BluRay",
    "Film.2023.2160p.HDR",
    "Movie.BG.Subs.1080p",  # Only subs, not audio
    "Film.2024.BGMI.1080p",  # BGMI is not BG Audio
    
    # Edge cases
    "Movie.2024.BG.WEB-DL",  # Ambiguous
    "Series.Background.Music.1080p",  # False positive check
]

# Keywords from the implementation
audio_keywords = [
    "bg audio", "bgaudio", "bg-audio",
    "bg dub", "bgdub", "bg-dub",
    "бг аудио", "бг дублаж",
    "bulgarian audio", "bulgarian dub"
]

def normalize_text(text):
    """Normalize separators to spaces (same as implementation)"""
    text = text.lower()
    text = re.sub(r'[._\-]+', ' ', text)
    return text

def detect_bg_audio(stream_name):
    """Check if stream name contains BG audio keywords"""
    normalized = normalize_text(stream_name)
    for keyword in audio_keywords:
        if keyword in normalized:
            return True, keyword
    return False, None

# Analyze streams
print("=" * 80)
print("BULGARIAN AUDIO DETECTION TEST")
print("=" * 80)
print()

positive_detected = []
negative_detected = []
false_positives = []
false_negatives = []

for stream in test_streams:
    detected, matched_keyword = detect_bg_audio(stream)
    is_positive_case = any(kw in stream.lower().replace('.', ' ').replace('-', ' ').replace('_', ' ') 
                          for kw in ['bg audio', 'bgaudio', 'bg dub', 'bgdub', 'бг аудио', 'бг дублаж', 'bulgarian audio', 'bulgarian dub'])
    
    if detected and is_positive_case:
        positive_detected.append((stream, matched_keyword))
    elif not detected and not is_positive_case:
        negative_detected.append(stream)
    elif detected and not is_positive_case:
        false_positives.append((stream, matched_keyword))
    elif not detected and is_positive_case:
        false_negatives.append(stream)

print("✅ CORRECTLY DETECTED (Positive Cases):")
for stream, keyword in positive_detected:
    print(f"  🔊 {stream}")
    print(f"     → Matched: '{keyword}'")
print()

print("✅ CORRECTLY IGNORED (Negative Cases):")
for stream in negative_detected:
    print(f"  ⚪ {stream}")
print()

if false_positives:
    print("⚠️  FALSE POSITIVES:")
    for stream, keyword in false_positives:
        print(f"  ❌ {stream}")
        print(f"     → Incorrectly matched: '{keyword}'")
    print()

if false_negatives:
    print("⚠️  FALSE NEGATIVES:")
    for stream in false_negatives:
        print(f"  ❌ {stream}")
    print()

# Statistics
total = len(test_streams)
correct = len(positive_detected) + len(negative_detected)
accuracy = (correct / total) * 100

print("=" * 80)
print(f"STATISTICS:")
print(f"  Total streams tested: {total}")
print(f"  Correctly identified: {correct} ({accuracy:.1f}%)")
print(f"  False positives: {len(false_positives)}")
print(f"  False negatives: {len(false_negatives)}")
print("=" * 80)
