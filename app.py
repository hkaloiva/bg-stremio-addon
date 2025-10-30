
@app.get("/test-subsland")
async def test_subsland():
    import subprocess
    result = subprocess.getoutput("curl -I https://subsland.com/downloadsubtitles/Game.of.Thrones.S06E01.The.Red.Woman.1080p.WEB-DL.DD5.1.H.264-NTb.rar")
    return {"result": result}

