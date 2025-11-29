// Validate TMDB Key
async function validateTMDBKey(apiKey) {
  try {
    const res = await fetch(`https://api.themoviedb.org/3/configuration?api_key=${apiKey}`);
    if (!res.ok) return false;
    return true;
  } catch (error) {
    return false;
  }
}

// Show error message
function showError(message) {
    let errorBox = document.getElementById("error-box");
    if (!errorBox) {
        errorBox = document.createElement("div");
        errorBox.id = "error-box";
        Object.assign(errorBox.style, {
            position: "fixed",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            background: "rgba(255, 0, 80, 0.95)",
            color: "#fff",
            padding: "16px 28px",
            borderRadius: "12px",
            fontWeight: "bold",
            boxShadow: "0 0 20px rgba(255,0,120,0.5)",
            fontFamily: "'Share Tech Mono', monospace",
            textShadow: "0 0 6px rgba(255,255,255,0.4)",
            zIndex: "9999",
            transition: "opacity 0.4s ease, transform 0.4s ease",
            opacity: "0",
        });
        document.body.appendChild(errorBox);


        requestAnimationFrame(() => {
            errorBox.style.opacity = "1";
            errorBox.style.transform = "translate(-50%, -50%) scale(1)";
        });
    }

    errorBox.textContent = message;


    setTimeout(() => {
        errorBox.style.opacity = "0";
        errorBox.style.transform = "translate(-50%, -50%) scale(0.9)";
        setTimeout(() => errorBox.remove(), 400);
    }, 4000);
}

function showSuccess(message) {
    let successBox = document.getElementById("success-box");
    if (!successBox) {
        successBox = document.createElement("div");
        successBox.id = "success-box";
        Object.assign(successBox.style, {
            position: "fixed",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%) scale(0.9)",
            background: "rgba(0, 200, 100, 0.95)",
            color: "#fff",
            padding: "16px 28px",
            borderRadius: "12px",
            fontWeight: "bold",
            boxShadow: "0 0 20px rgba(0,255,120,0.5)",
            fontFamily: "'Share Tech Mono', monospace",
            textShadow: "0 0 6px rgba(255,255,255,0.4)",
            zIndex: "9999",
            transition: "opacity 0.4s ease, transform 0.4s ease",
            opacity: "0",
        });
        document.body.appendChild(successBox);

        requestAnimationFrame(() => {
            successBox.style.opacity = "1";
            successBox.style.transform = "translate(-50%, -50%) scale(1)";
        });
    }

    successBox.textContent = message;

    setTimeout(() => {
        successBox.style.opacity = "0";
        successBox.style.transform = "translate(-50%, -50%) scale(0.9)";
        setTimeout(() => successBox.remove(), 400);
    }, 4000);
}

function showLoader() {
    let loader = document.getElementById("loader-susp");

    // Se non esiste, crealo e applica lo stile
    if (!loader) {
        loader = document.createElement("div");
        loader.id = "loader-susp";

        Object.assign(loader.style, {
            border: "6px solid rgba(255, 255, 255, 0.2)",
            borderTop: "6px solid #00fff0",  // colore neon
            borderRadius: "50%",
            width: "50px",
            height: "50px",
            position: "fixed",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            zIndex: "9998",
            animation: "spin 1s linear infinite",
            opacity: "0",
            transition: "opacity 0.3s ease",
        });
        document.body.appendChild(loader);
    }

    // Mostra con dissolvenza
    requestAnimationFrame(() => {
        loader.style.opacity = "1";
    });
}

function hideLoader() {
    const loader = document.getElementById("loader-susp");
    if (loader) {
        loader.style.opacity = "0";
        setTimeout(() => loader.remove(), 300); // aspetta la dissolvenza
    }
}
