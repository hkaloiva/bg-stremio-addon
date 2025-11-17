/*
const addonBlackList = [
    "org.stremio.mammamia",                 // Mamma Mia
    "com.linvo.stremiochannels",            // Youtube
    "org.community.orion",                  // Orion
    "stremio.addons.mediafusion|elfhosted", // MediaFusion Elfhosted
    "org.stremio.thepiratebay-catalog",     // TPB Catalog
    "org.zoropogaddon",                     // One Piece Catalog
    "com.noone.stremio-trakt-up-next",      // Trakt Up Next
    "community.usatv",                      // USA TV
    "community.argentinatv",                // Argentina TV
    "tmdb-addon",                           // TMDB Addon
    "pw.ers.concerts"                       // Music Concerts
]
*/

const compatibilityList = [
    "com.linvo.cinemeta",               // Cinemeta
    "community.anime.kitsu",            // Kitsu 
    "org.stremio.animecatalogs",        // Anime Catalogs
    "marcojoao.ml.cyberflix.catalog",   // Cyberflix Catalogs
    "pw.ers.netflix-catalog",           // Streaming Catalogs
    "org.trakt.",                       // Trakt Stremio Official
    "community.trakt-tv",               // Trakt TV
    "org.stremio.pubdomainmovies",      // Public Domains
    "org.imdbcatalogs",                 // IMDB Catalogs
    "org.imdbcatalogs.rpdb",            // IMDB Catalogs (with ratings)
    "pw.ers.rottentomatoes",            // Rotten Tomatoes Catalogs
    "com.mdblist.",                     // MDBLists Catalogs
    //"com.sagetendo.mal-stremio-addon",  // MAL Addon
    "dev.filmwhisper.",                 // AI Film Whisper
    "community.anime.kitsu.search",     // Kitsu search addon
    "com.joaogonp.marveladdon",        // Marvel addon
    "github.megadrive.stremio.letterboxd" // Letterboxd addon
    //"org.stremio.aiolists"              //AIO Lists
]

let addonCardCounter = 0;

function isCompatible(manifest) {
    if (!manifest || !manifest.id) return false;
    if (compatibilityList.some(id => manifest.id.startsWith(id))) {
        return true;
    }
    // Fallback: allow generic catalog-providing manifests
    if (Array.isArray(manifest.resources)) {
        const names = manifest.resources.map(r => {
            if (typeof r === "string") return r;
            if (r && typeof r === "object") return r.name || "";
            return "";
        });
        if (names.includes("catalog")) {
            return true;
        }
    }
    return false;
}


function normalizeAddonUrl(rawUrl) {
    if (!rawUrl) return "";
    let url = rawUrl.trim();
    if (url.startsWith("stremio://")) {
        url = "https://" + url.slice("stremio://".length);
    }
    if (url.startsWith("//")) {
        url = "https:" + url;
    }
    // If user pasted a configure page, try the manifest endpoint
    if (url.endsWith("/configure")) {
        url = url.replace(/\/configure$/, "/manifest.json");
    }
    return url;
}

async function loadAddon(url, _showError=false, type="default", appendNow=true) {
    const normalizedUrl = normalizeAddonUrl(url);
    if (!normalizedUrl) {
        showError("❌ Invalid URL.");
        return null;
    }

    try {
        const response = await fetch(normalizedUrl);
        if (!response.ok) {
            if (_showError) showError(`❌ Error: ${response.status}`);
            return null;
        }

        const manifest = await response.json();
        const serverUrl = window.location.origin;

        if (!isCompatible(manifest)) {
            if (_showError) showError("❌ Incompatible addon.");
            return null;
        }

        if ("translated" in manifest && !normalizedUrl.includes(serverUrl)) {
            return null;
        }

        // Return the element without immediately appending
        return createAddonCard(manifest, normalizedUrl, type, appendNow);

    } catch (error) {
        console.log(error);
        if (_showError) showError("❌ Failed to load addon manifest.");
        return null;
    }
}

function makeAddonKey(manifest, url) {
    const base = (manifest.id || manifest.name || "addon").replace(/[^a-zA-Z0-9_-]/g, "");
    const shortHash = btoa(url).replace(/[^a-zA-Z0-9]/g, "");
    const unique = `${addonCardCounter++}-${shortHash.slice(-8)}`;
    return `${base}-${unique}`;
}

function createAddonCard(manifest, url, type="default", appendNow=true) {
    const container = document.getElementById("addons-container");
    const cardKey = makeAddonKey(manifest, url);

    const addonCard = document.createElement("div");
    addonCard.className = "addon-info";
    addonCard.dataset.cardKey = cardKey;

    addonCard.appendChild(createAddonHeader(manifest));
    addonCard.appendChild(createAddonDescription(manifest));
    addonCard.appendChild(createAddonVersion(manifest));
    //addonCard.appendChild(createSkipPosterOption(manifest));
    addonCard.appendChild(createRPDBOption(manifest, cardKey));
    addonCard.appendChild(createToastRatingsOption(manifest, cardKey));
    addonCard.appendChild(createTopStreamPosterOption(manifest, cardKey));

    // Rende checkbox esclusive
    makePosterOptionsExclusive(addonCard);

    const actionsDiv = document.createElement("div");
    actionsDiv.className = "addon-actions";

    if (type == "default") {
        const installBtn = createInstallButton(manifest, url, cardKey);
        actionsDiv.appendChild(installBtn);
    } else if (type == "generator") {
        const generateBtn = createGenerateButton(manifest, url, cardKey);
        const copyBtn = createCopyButton(manifest, url, cardKey);
        actionsDiv.appendChild(generateBtn);
        actionsDiv.appendChild(copyBtn);
        addonCard.appendChild(createLinkTextBox("", manifest, cardKey));
    }

    addonCard.appendChild(actionsDiv);

    if (appendNow) container.appendChild(addonCard);

    return addonCard; // always return the element
}

function createAddonHeader(manifest) {
    const addonHeader = document.createElement("div");
    addonHeader.className = "addon-header";

    const logo = document.createElement("img");
    logo.className = "addon-logo";
    logo.src = manifest.logo || "static/img/addon_logo.png";
    logo.alt = "Addon logo";
    addonHeader.appendChild(logo);

    const title = document.createElement("h3");
    title.innerText = manifest.name || "N/A";
    addonHeader.appendChild(title);

    return addonHeader;
}

function createAddonDescription(manifest) {
    const description = document.createElement("p");
    description.innerHTML = `<strong>Description:</strong> ${manifest.description || "N/A"}`;
    return description;
}

function createAddonVersion(manifest) {
    const version = document.createElement("p");
    version.innerHTML = `<strong>Version:</strong> ${manifest.version || "N/A"}`;
    return version;
}

function createSkipPosterOption(manifest) {
    const skipPosterDiv = document.createElement("div");
    skipPosterDiv.className = "skip-poster";

    const skipPosterCheckbox = document.createElement("input");
    skipPosterCheckbox.type = "checkbox";
    skipPosterCheckbox.id = `skipPoster-${manifest.name}`;
    skipPosterDiv.appendChild(skipPosterCheckbox);

    const skipPosterLabel = document.createElement("label");
    skipPosterLabel.htmlFor = `skipPoster-${manifest.name}`;
    skipPosterLabel.innerText = "Skip Poster";
    skipPosterDiv.appendChild(skipPosterLabel);

    return skipPosterDiv;
}

function createRPDBOption(manifest, key) {
    const rpdbDiv = document.createElement("div");
    rpdbDiv.className = "rpdb";

    const rpdbCheckbox = document.createElement("input");
    rpdbCheckbox.type = "checkbox";
    rpdbCheckbox.id = `rpdb-${key}`;
    rpdbDiv.appendChild(rpdbCheckbox);

    const rpdbLabel = document.createElement("label");
    rpdbLabel.htmlFor = `rpdb-${key}`;
    rpdbLabel.innerText = "RPDB Posters";
    rpdbDiv.appendChild(rpdbLabel);

    return rpdbDiv;
}

function createToastRatingsOption(manifest, key) {
    const toastRatingsDiv = document.createElement("div");
    toastRatingsDiv.className = "toast-ratings";

    const toastRatingsCheckbox = document.createElement("input");
    toastRatingsCheckbox.type = "checkbox";
    toastRatingsCheckbox.id = `toastRatings-${key}`;
    toastRatingsDiv.appendChild(toastRatingsCheckbox);

    const toastRatingsLabel = document.createElement("label");
    toastRatingsLabel.htmlFor = `toastRatings-${key}`;
    toastRatingsLabel.innerText = "Toast Ratings Posters";
    toastRatingsDiv.appendChild(toastRatingsLabel);

    return toastRatingsDiv;
}

function createTopStreamPosterOption(manifest, key) {
    const tsPosterDiv = document.createElement("div");
    tsPosterDiv.className = "tsPoster";

    const tsPosterCheckbox = document.createElement("input");
    tsPosterCheckbox.type = "checkbox";
    tsPosterCheckbox.id = `tsPoster-${key}`;
    tsPosterDiv.appendChild(tsPosterCheckbox);

    const tsPosterLabel = document.createElement("label");
    tsPosterLabel.htmlFor = `tsPoster-${key}`;
    tsPosterLabel.innerText = "Top Streaming Posters";
    tsPosterDiv.appendChild(tsPosterLabel);

    return tsPosterDiv;
}

function createInstallButton(manifest, url, key) {
    const installBtn = document.createElement("button");
    installBtn.className = "install-btn";
    installBtn.innerText = "Select";
    installBtn.state = "active";
    installBtn.style.backgroundColor = "#2ecc71";
    installBtn.onclick = () => toggleAddonSelection(installBtn, manifest, url, key);
    return installBtn;
}

function createGenerateButton(manifest, url, key) {
    const generateBtn = document.createElement("button");
    generateBtn.className = "generate-btn";
    generateBtn.innerText = "Generate link";
    generateBtn.onclick = async () => {
        await generateLinkByCard(manifest, url, generateTranslatorLink, key);
    };
    return generateBtn;
}

function createCopyButton(manifest, url, key) {
    const generateBtn = document.createElement("button");
    generateBtn.className = "copy-btn";
    generateBtn.innerText = "Copy link";
    generateBtn.onclick = () => copyLinkCard(manifest, key);
    return generateBtn;
}

function createLinkTextBox(link, manifest, key) {
    const textArea = document.createElement("textarea");
    textArea.className = "read-only-textarea";
    textArea.id = `linkBox-${key}`;
    textArea.readOnly = true; 
    textArea.value = link;
    return textArea;
}

function toggleAddonSelection(installBtn, manifest, url, key) {
    //const spCheckbox = document.getElementById(`skipPoster-${manifest.name}`);
    const rpdbCheckbox = document.getElementById(`rpdb-${key}`);
    const trCheckbox = document.getElementById(`toastRatings-${key}`);
    const tsCheckbox = document.getElementById(`tsPoster-${key}`)
    if (installBtn.state === "active") {
        installBtn.state = "not_active";
        installBtn.innerText = "Remove";
        installBtn.style.backgroundColor = "#ff4b4b";
        
        //const skipQuery = spCheckbox.checked ? 1 : 0;
        const rpdbQuery = rpdbCheckbox.checked ? 1 : 0;
        const rateQuery = trCheckbox.checked ? 1 : 0;
        const tsQuery = tsCheckbox.checked ? 1 : 0;
        //spCheckbox.disabled = true;
        rpdbCheckbox.disabled = true;
        trCheckbox.disabled = true;
        tsCheckbox.disabled = true;
        manifest.transportUrl = url;
        //manifest.skipPoster = skipQuery;
        manifest.rpdb = rpdbQuery;
        manifest.toastRatings = rateQuery;
        manifest.tsPoster = tsQuery;
        transteArray.push(manifest);
    } else {
        //spCheckbox.disabled = false;
        rpdbCheckbox.disabled = false;
        trCheckbox.disabled = false;
        tsCheckbox.disabled = false;
        installBtn.state = "active";
        installBtn.innerText = "Select";
        installBtn.style.backgroundColor = "#2ecc71";
        
        // Remove from translation selections
        transteArray = transteArray.filter(item => item !== manifest);
    }
}

async function copyLinkCard(manifest, key) {
    const linkBox = document.getElementById(`linkBox-${key}`);
    await navigator.clipboard.writeText(linkBox.value);
    showSuccess('✅ Link copied!');
}

async function generateLinkByCard(manifest, url, linkGeneratorFunc, key) {

    // Check TMDB API Key validity
    const tmdbApiKey = document.getElementById("tmdb-key").value;

    if (!tmdbApiKey) {
        showError("⚠️ Please enter a TMDB API Key before continuing!");
        return null;
    }

    const valid = await validateTMDBKey(tmdbApiKey);
    console.log(valid)
    if (!valid) {
        showError("❌ Invalid TMDB API Key. Please check your key and try again.");
        return null;
    }

    //
    //const spCheckbox = document.getElementById(`skipPoster-${manifest.name}`);
    const rpdbCheckbox = document.getElementById(`rpdb-${key}`);
    const trCheckbox = document.getElementById(`toastRatings-${key}`);
    const tsCheckbox = document.getElementById(`tsPoster-${key}`);
    const linkBox = document.getElementById(`linkBox-${key}`)
    //const skipQuery = spCheckbox.checked ? 1 : 0;
    const rpdbQuery = rpdbCheckbox.checked ? 1 : 0;
    const rateQuery = trCheckbox.checked ? 1 : 0;
    const tsQuery = tsCheckbox.checked ? 1 : 0;
    const link = linkGeneratorFunc(url, rpdbQuery, rateQuery, tsQuery);
    
    linkBox.value = link;
    linkBox.style.opacity = 100;
    linkBox.style.height = "auto";
    linkBox.style.height = (linkBox.scrollHeight) + "px";
}


function makePosterOptionsExclusive(addonCard) {
    const posterCheckboxes = addonCard.querySelectorAll(
        '.rpdb input, .toast-ratings input, .tsPoster input'
    );

    posterCheckboxes.forEach(chk => {
        chk.addEventListener('change', () => {
            if (chk.checked) {
                posterCheckboxes.forEach(other => {
                    if (other !== chk) other.checked = false;
                });
            }
        });
    });
}
