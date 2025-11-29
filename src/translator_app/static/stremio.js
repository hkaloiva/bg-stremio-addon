var stremioUser;

async function stremioLogin() {
    const email = document.getElementById("stremio-email").value;
    const password = document.getElementById("stremio-password").value;
    const loginUrl = "https://api.strem.io/api/login";
    const loginData = {
        "type": "Auth",
        "type": "Login",
        "email": email,
        "password": password,
        "facebook": false
    }
    const response = await fetch(loginUrl, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(loginData)
    })
    .then(response => response.json());
    
    if (response.error) {
        showError("❌ " + response.error.message);
    } else {
        stremioUser = response;
        document.getElementById("desc-head").style.display = "none";
        document.querySelector(".login-group").style.display = "none";
        document.querySelector(".add-group").style.display = "flex";
        document.querySelector(".config-group").style.display = "flex";
        document.querySelector(".translate-button").style.visibility = "visible";
        await stremioLoadAddons(response.result.authKey);
    }
}

async function stremioLoadAddons(authKey) {
    const loader = document.querySelector(".loader");
    loader.style.display = "flex";

    const container = document.getElementById("addons-container");
    const addonCollection = await stremioAddonCollectionGet(authKey);
    const addons = addonCollection.result.addons;

    // Carica tutti in parallelo e aspetta i risultati
    const results = await Promise.all(addons.map(addon => loadAddon(addon.transportUrl, false, "default", false)));

    // Aggiungi al DOM solo quelli validi, nell'ordine corretto
    results.forEach(card => {
        if(card) container.appendChild(card);
    });

    loader.style.display = "none";
}

async function stremioAddonCollectionGet(authKey) {
    const addonCollectionUrl = "https://api.strem.io/api/addonCollectionGet"

    const payload = {
        "type": "AddonCollectionGet",
        "authKey": authKey,
        "update": true
    }

    const response = await fetch(addonCollectionUrl, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    });

    return await response.json();
}

async function stremioAddonCollectionSet(authKey, addonList) {
    const addonCollectionUrl = "https://api.strem.io/api/addonCollectionSet"

    const payload = {
        "type": "AddonCollectionSet",
        "authKey": authKey,
        "addons": addonList
    }

    const response = await fetch(addonCollectionUrl, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    });

    return await response.json();
}