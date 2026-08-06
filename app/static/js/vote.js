/* Public Perception Index — community sentiment voting.
 *
 * The anonymous voter token is a random UUID with no derivation from anything
 * about the device or the person. It is written to localStorage only at the
 * moment someone actually votes: a reader who never votes leaves no trace, so
 * merely viewing the page stores nothing. Withdrawing a vote removes the token
 * as well, which is what makes "withdraw" mean withdrawn rather than hidden.
 */
(function () {
  'use strict';

  var API = '/api/hormuz-index/sentiment';
  var TOKEN_KEY = 'hmx_voter_token';

  var block = document.getElementById('ppi-block');
  var dialog = document.getElementById('ppi-dialog');
  if (!block || !dialog || typeof dialog.showModal !== 'function') return;

  var openBtn = document.getElementById('ppi-open');
  var openLabel = document.getElementById('ppi-open-label');
  var slider = document.getElementById('ppi-slider');
  var sliderValue = document.getElementById('ppi-slider-value');
  var sliderWord = document.getElementById('ppi-slider-word');
  var sliderMapped = document.getElementById('ppi-slider-mapped');
  var submitBtn = document.getElementById('ppi-submit');
  var withdrawBtn = document.getElementById('ppi-withdraw');
  var errorEl = document.getElementById('ppi-error');

  var valueEl = document.getElementById('ppi-value');
  var levelEl = document.getElementById('ppi-level');
  var countEl = document.getElementById('ppi-count');
  var gapEl = document.getElementById('ppi-gap');
  var fillEl = document.getElementById('ppi-fill');
  var pointerEl = document.getElementById('ppi-pointer');
  var meterEl = document.getElementById('ppi-meter');

  var RATING_MIN = 1;
  var RATING_MAX = 10;
  var SCALE_MIN = 100;
  var SCALE_MAX = 200;

  var modelScore = parseFloat(block.dataset.modelScore) || SCALE_MIN;
  var myVote = null;

  /* Responses can land out of order: a vote posted while the page-load refresh
     is still in flight would otherwise be overwritten by that older, pre-vote
     aggregate. Only ever render a response newer than the last one drawn. */
  var issued = 0;
  var rendered = 0;

  /* One phrase per rating, escalation-ordered, so the control reads as a
     judgement about the situation rather than an abstract number out of ten. */
  var WORDS = [
    '',                          // index 0 unused; ratings start at 1
    'Calm — business as usual',
    'Background friction',
    'Rising rhetoric',
    'Elevated tension',
    'Serious escalation risk',
    'Tense standoff',
    'Shipping under threat',
    'On the brink',
    'Conflict under way',
    'Open war'
  ];

  function wordFor(v) {
    return WORDS[v] || WORDS[1];
  }

  /* Same mapping the server applies to the mean, so the dialog can show where a
     rating lands before it is submitted. Duplicated deliberately: a preview is
     not worth a round trip on every slider nudge. */
  function ratingToIndex(v) {
    var fraction = (v - RATING_MIN) / (RATING_MAX - RATING_MIN);
    return SCALE_MIN + fraction * (SCALE_MAX - SCALE_MIN);
  }

  /* --- Token ------------------------------------------------------------ */

  function readToken() {
    try {
      return window.localStorage.getItem(TOKEN_KEY);
    } catch (e) {
      return null; // private mode / storage blocked — voting degrades to none
    }
  }

  function ensureToken() {
    var existing = readToken();
    if (existing) return existing;
    var token;
    if (window.crypto && window.crypto.randomUUID) {
      token = window.crypto.randomUUID();
    } else {
      var bytes = new Uint8Array(16);
      window.crypto.getRandomValues(bytes);
      token = Array.prototype.map
        .call(bytes, function (b) { return ('0' + b.toString(16)).slice(-2); })
        .join('');
    }
    try {
      window.localStorage.setItem(TOKEN_KEY, token);
    } catch (e) {
      return null;
    }
    return token;
  }

  function clearToken() {
    try {
      window.localStorage.removeItem(TOKEN_KEY);
    } catch (e) { /* nothing to clear */ }
  }

  /* --- Rendering -------------------------------------------------------- */

  function request(method, body) {
    var headers = { 'Accept': 'application/json' };
    var token = method === 'GET' ? readToken() : ensureToken();
    if (token) headers['X-Voter-Token'] = token;
    if (body) headers['Content-Type'] = 'application/json';

    var seq = ++issued;
    return fetch(API, {
      method: method,
      headers: headers,
      body: body ? JSON.stringify(body) : undefined
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok) throw new Error(data.error || 'Request failed.');
        data._seq = seq;
        return data;
      });
    });
  }

  function render(data) {
    if (data._seq && data._seq < rendered) return;
    rendered = data._seq || rendered;

    myVote = typeof data.your_vote === 'number' ? data.your_vote : null;

    if (data.index === null || data.index === undefined) {
      valueEl.textContent = '—';
      levelEl.hidden = true;
      gapEl.hidden = true;
      pointerEl.hidden = true;
      fillEl.style.width = '0%';
      countEl.textContent = data.available
        ? (data.votes > 0 ? data.votes + ' vote' + (data.votes === 1 ? '' : 's') + ' this week' : '0 votes this week')
        : 'Voting unavailable';
    } else {
      valueEl.textContent = data.index.toFixed(1);
      levelEl.hidden = false;
      levelEl.textContent = (data.level_label || '').toUpperCase();
      levelEl.className = 'status-badge status-' + (data.level_status || 'good');
      countEl.textContent =
        data.votes + ' vote' + (data.votes === 1 ? '' : 's') + ' this week';

      fillEl.style.width = data.scale_pct + '%';
      pointerEl.hidden = false;
      pointerEl.style.left = data.scale_pct + '%';
      meterEl.setAttribute('aria-valuenow', data.index.toFixed(1));

      var gap = data.index - modelScore;
      gapEl.hidden = false;
      gapEl.innerHTML = '';
      var gapValue = document.createElement('span');
      gapValue.className =
        'ppi-gap-value ' + (gap > 0 ? 'is-hotter' : 'is-cooler');
      gapValue.textContent = (gap > 0 ? '+' : '') + gap.toFixed(1);
      var gapLabel = document.createElement('span');
      gapLabel.className = 'ppi-gap-label';
      gapLabel.textContent = 'vs model score';
      gapEl.appendChild(gapValue);
      gapEl.appendChild(gapLabel);
    }

    openLabel.textContent = myVote === null ? 'Cast your read' : 'Change your vote';
    withdrawBtn.hidden = myVote === null;
    if (myVote !== null) setSlider(myVote);

    if (!data.available) {
      openBtn.disabled = true;
      openBtn.title = 'Voting is temporarily unavailable.';
    }
  }

  function setSlider(v) {
    slider.value = v;
    sliderValue.textContent = v;
    sliderWord.textContent = wordFor(v);
    sliderMapped.textContent =
      '= ' + ratingToIndex(v).toFixed(1) + ' on the index scale';
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  function busy(state) {
    submitBtn.disabled = state;
    withdrawBtn.disabled = state;
    submitBtn.textContent = state ? 'Saving…' : 'Submit vote';
  }

  function track(name, params) {
    if (typeof window.trackEvent === 'function') {
      window.trackEvent(name, params);
    } else if (typeof window.gtag === 'function') {
      window.gtag('event', name, Object.assign({ page_path: location.pathname }, params || {}));
    }
  }

  /* --- Wiring ----------------------------------------------------------- */

  slider.addEventListener('input', function () {
    setSlider(parseInt(slider.value, 10));
  });

  openBtn.addEventListener('click', function () {
    errorEl.hidden = true;
    /* Open on the reader's own last answer when they have one, otherwise on the
       midpoint rather than on the model score — anchoring the slider to the
       published number would bias the very thing being measured. */
    setSlider(myVote === null ? 5 : myVote);
    dialog.showModal();
    track('ppi_dialog_open', { report_slug: 'hormuz-index', page_path: location.pathname });
  });

  submitBtn.addEventListener('click', function () {
    errorEl.hidden = true;
    var value = parseInt(slider.value, 10);
    var isEdit = myVote !== null;
    var previousValue = myVote;
    busy(true);
    request('POST', { value: value })
      .then(function (data) {
        render(data);
        dialog.close();
        var mapped = ratingToIndex(value);
        var word = wordFor(value);
        track('ppi_vote_submit', {
          rating_value: value,
          mapped_score: Math.round(mapped * 10) / 10,
          sentiment_word: word,
          is_edit: isEdit,
          previous_value: previousValue,
          report_slug: 'hormuz-index',
          page_path: location.pathname
        });
      })
      .catch(function (err) {
        showError(err.message);
      })
      .then(function () {
        busy(false);
      });
  });

  withdrawBtn.addEventListener('click', function () {
    errorEl.hidden = true;
    busy(true);
    request('DELETE')
      .then(function (data) {
        clearToken();
        data.your_vote = null;
        render(data);
        dialog.close();
        track('ppi_vote_withdraw', { report_slug: 'hormuz-index', page_path: location.pathname });
      })
      .catch(function (err) {
        showError(err.message);
      })
      .then(function () {
        busy(false);
      });
  });

  /* The page is CDN-cached, so the server-rendered figures can be up to half an
     hour stale and never know about this browser's own vote. Refresh from the
     no-store endpoint on load. */
  request('GET').then(render).catch(function () { /* keep the rendered fallback */ });
})();
