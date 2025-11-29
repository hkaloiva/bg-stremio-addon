# Bulgarian Audio Detection - Rollback Plan

## Feature Summary
This feature adds detection and visual flagging (🔊) for streams with Bulgarian audio tracks, alongside the existing Bulgarian subtitle detection (🇧🇬).

## Changes Made
1. **stream_probe.py**: Enhanced to probe audio tracks in addition to subtitles
2. **stream_enricher.py**: Added `_mark_bg_content()` to detect BG audio via filename keywords and probe results
3. **Priority**: BG Audio streams are now prioritized above BG Subtitle streams
4. **Tests**: New file `tests/test_audio_detection.py` with 3 test cases

## Rollback Procedures

### Option 1: Branch Rollback (Safest)
If the feature causes issues in production:

```bash
cd /Users/kaloyanivanov/Toast\ Translator/toast-translator
git checkout main
git branch -D feature/bg-audio-detection  # Delete the feature branch
./deploy-koyeb.sh da6bf2d2
```

**Time**: ~3-5 minutes  
**Risk**: None (reverts to stable main branch)

### Option 2: Selective File Revert (If partially broken)
If only specific functionality is broken:

```bash
# Revert audio detection but keep other changes
git checkout main -- src/translator_app/stream_probe.py
git checkout main -- src/translator_app/services/stream_enricher.py
git checkout main -- tests/test_audio_detection.py
git commit -m "Revert audio detection feature"
git push origin feature/bg-audio-detection
./deploy-koyeb.sh da6bf2d2
```

**Time**: ~2 minutes  
**Risk**: Low (surgical revert)

### Option 3: Environment Variable Disable (Quickest)
The stream probe functionality can be disabled via environment variable without code changes:

**In Koyeb Dashboard**:
1. Go to Service Settings > Environment Variables
2. Set `STREAM_SUBS_PROBE=0`
3. Redeploy

**Time**: ~30 seconds  
**Risk**: Minimal (disables probing but keeps other enrichment)

### Option 4: Git Revert Commit (Traceable)
Create a revert commit for audit trail:

```bash
git revert HEAD
git push origin feature/bg-audio-detection
./deploy-koyeb.sh da6bf2d2
```

**Time**: ~1 minute  
**Risk**: Low (git preserves full history)

## Monitoring & Validation

### Key Metrics to Watch
1. **Stream Enrichment Latency**: Should remain < 2s for Level 1, < 10s for Level 2
2. **ffprobe Success Rate**: Check logs for timeout/failure rates
3. **Cache Hit Rate**: Monitor `stream_subs` cache performance
4. **User Reports**: Look for incorrect flags or missing audio streams

### Test Commands
```bash
# Local smoke test
PYTHONPATH=. pytest tests/test_audio_detection.py

# Full test suite
PYTHONPATH=. pytest

# Verify deployment
python verify_koyeb.py
```

### Known Safe Fallbacks
- The feature gracefully degrades if `ffprobe` is unavailable
- Probe timeouts (10s default) prevent hanging
- Empty or malformed results are caught and ignored

## Deployment Strategy

### Recommended Approach
1. **Test locally** with `PYTHONPATH=. pytest`
2. **Merge to main** only after thorough testing
3. **Monitor Koyeb logs** for first 15 minutes post-deploy
4. **Spot check** a few streams manually in Stremio

### Rollback Decision Tree
```
Is probe causing timeouts/errors?
├─ YES → Set STREAM_SUBS_PROBE=0 (Option 3)
└─ NO
    └─ Are audio flags incorrect?
        ├─ YES → Selective file revert (Option 2)
        └─ NO
            └─ Is entire feature problematic?
                └─ YES → Branch rollback (Option 1)
```

## Contact & Support
- Feature branch: `feature/bg-audio-detection`
- Commit hash: `85ea312`
- Test coverage: 3 new tests (48 total passing)
- Deploy script: `./deploy-koyeb.sh da6bf2d2`
