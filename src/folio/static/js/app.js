/* Folio custom JavaScript */

// Theme management (light/dark toggle, defaults to browser preference)
(function() {
    var THEME_KEY = 'folio-theme';
    var html = document.documentElement;

    function getSystemTheme() {
        return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function getCurrentTheme() {
        return localStorage.getItem(THEME_KEY) || getSystemTheme();
    }

    function applyTheme(theme) {
        html.setAttribute('data-theme', theme);
    }

    // Apply immediately to prevent FOUC
    applyTheme(getCurrentTheme());

    document.addEventListener('DOMContentLoaded', function() {
        var checkbox = document.getElementById('mode-checkbox');
        if (!checkbox) return;

        checkbox.checked = (getCurrentTheme() === 'dark');

        checkbox.addEventListener('change', function() {
            html.classList.add('trans');
            var theme = checkbox.checked ? 'dark' : 'light';
            applyTheme(theme);
            localStorage.setItem(THEME_KEY, theme);
        });
    });

    // Respond to system preference changes when no stored preference
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
        if (!localStorage.getItem(THEME_KEY)) {
            var theme = getSystemTheme();
            applyTheme(theme);
            var checkbox = document.getElementById('mode-checkbox');
            if (checkbox) checkbox.checked = (theme === 'dark');
        }
    });
})();

// Auto-dismiss flash messages after 5 seconds
document.addEventListener('DOMContentLoaded', function() {
    var flashes = document.querySelectorAll('.flash');
    flashes.forEach(function(flash) {
        setTimeout(function() {
            flash.style.transition = 'opacity 0.5s';
            flash.style.opacity = '0';
            setTimeout(function() {
                flash.remove();
            }, 500);
        }, 5000);
    });
});

// Send browser timezone with all requests
(function() {
    var tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    document.body.setAttribute('hx-headers', JSON.stringify({'X-Timezone': tz}));
    document.cookie = 'tz=' + tz + ';path=/;SameSite=Lax';
})();
