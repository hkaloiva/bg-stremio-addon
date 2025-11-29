function flagFromCountry(country) {
    return country
        .toUpperCase()
        .split('')
        .map(c => String.fromCodePoint(127397 + c.charCodeAt(0)))
        .join('');
}

const select = document.getElementById('language');

fetch('languages.json')
    .then(response => response.json())
    .then(locales_main => {
        locales_main.forEach(locale => {
            const [lang, country] = locale.split('-');

            let languageName;
            try {
                languageName = new Intl.DisplayNames([lang], { type: 'language' }).of(lang);
            } catch {
                languageName = lang;
            }

            const flag = flagFromCountry(country);

            const option = document.createElement('option');
            option.value = locale;
            option.textContent = `${flag} ${languageName} (${locale})`;
            select.appendChild(option);
        });
    })
    .catch(err => console.error('Error on load languages.json:', err));
