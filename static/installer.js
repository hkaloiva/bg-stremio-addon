var transteArray = [];

function sanitizeAlias(raw) {
    if (!raw) return "";
    const cleaned = raw.trim().toLowerCase().replace(/[^a-z0-9_-]/g, "");
    return cleaned.slice(0, 40);
}

async function translateSelected(authKey, selectList) {

    // ✅ Check TMDB API Key validity
    const tmdbApiKey = document.getElementById("tmdb-key").value;
    showLoader();
    if (!tmdbApiKey) {
        showError("⚠️ Please enter a TMDB API Key before continuing!");
        hideLoader();
        return null;
    }

    const valid = await validateTMDBKey(tmdbApiKey);
    if (!valid) {
        showError("❌ Invalid TMDB API Key. Please check your key and try again.");
        hideLoader();
        return null;
    }

    const collection = await stremioAddonCollectionGet(authKey);
    var addons = [];

    for (var i = 0; i < collection.result.addons.length; i++) {
        addons.push({
            "manifest": collection.result.addons[i].manifest,
            "transportUrl": collection.result.addons[i].transportUrl,
            "flags": {
                "official": false,
                "protected": false
            }
        });
    }

    for (var j = 0; j < selectList.length; j++) {
        for (var i = 0; i < addons.length; i++) {
            if (selectList[j].id == addons[i].manifest.id) {
                var addonUrl = await generateTranslatorLink(addons[i].transportUrl, selectList[j].rpdb, selectList[j].toastRatings, selectList[j].tsPoster);
                var response = await fetch(addonUrl);
                var tranlatorManifest = await response.json();
                addons[i] = {
                    "manifest": tranlatorManifest,
                    "transportUrl": addonUrl,
                    "flags": {
                        "official": false,
                        "protected": false
                    }
                };
                break;
            }
        }
        // Add new addon
        var addonUrl = await generateTranslatorLink(selectList[j].transportUrl, selectList[j].rpdb, selectList[j].toastRatings, selectList[j].tsPoster);
        var response = await fetch(addonUrl);
        var tranlatorManifest = await response.json();
        addons[i] = {
            "manifest": tranlatorManifest,
            "transportUrl": addonUrl,
            "flags": {
                "official": false,
                "protected": false
            }
        };
    }

    var resp = await stremioAddonCollectionSet(authKey, addons);
    if (resp.result.success == true) {
        hideLoader();
        showSuccess("✅ Addons installed successfully!");
        // Refresh addons
        await reloadAddons(authKey);
    }
}

async function reloadAddons(authKey) {
    transteArray = [];
    const addons = document.querySelectorAll(".addon-info");
    addons.forEach(addon => addon.remove());
    await stremioLoadAddons(authKey);
}

function generateTranslatorLink(addonUrl, rpdb, toast_ratings, tsPoster) {
    const serverUrl = window.location.origin;
    const baseAddonUrl = getBaseUrl(addonUrl).replace("/manifest.json", "");
    const urlEncoded = btoa(baseAddonUrl);
    const tmdbApiKey = document.getElementById("tmdb-key").value;
    const language = document.getElementById("language").value;
    let rpdbKey = document.getElementById("rpdb-key").value;
    const topPosterKey = document.getElementById("top-key").value;
    const aliasInput = document.getElementById("alias-key");
    const alias = aliasInput ? sanitizeAlias(aliasInput.value) : "";
    if (!rpdbKey) {
        rpdbKey = "t0-free-rpdb";
    }
    let userSettings = `rpdb=${rpdb},tr=${toast_ratings},tsp=${tsPoster},language=${language},tmdb_key=${tmdbApiKey}`;
    if (rpdb) {
        userSettings += `,rpdb_key=${rpdbKey}`
    }
    else if (tsPoster) {
        userSettings += `,topkey=${topPosterKey}`
    }
    if (alias) {
        userSettings += `,alias=${alias}`;
    }
    
    if (addonUrl.includes(serverUrl)) {
        const addonBase64String = addonUrl.split("/")[3];
        return `${serverUrl}/${addonBase64String}/${userSettings}/manifest.json`;
    }

    return `${serverUrl}/${urlEncoded}/${userSettings}/manifest.json`;
}

function getBaseUrl(urlString) {
    const url = new URL(urlString);
    return `${url.protocol}//${url.host}${url.pathname}`;
}
