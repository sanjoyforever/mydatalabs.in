/* Public Perception Index — community sentiment voting.
 *
 * Voting happens on the published gauge itself: the marker that shows where the
 * crowd sits is the same control you drag to say where you think it should sit.
 * Dragging only stages a value; nothing is recorded until the button is pressed,
 * so an accidental nudge costs nothing.
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
  var meterEl = document.getElementById('ppi-meter');
  var pointerEl = document.getElementById('ppi-pointer');
  if (!block || !meterEl || !pointerEl) return;

  var submitBtn = document.getElementById('ppi-submit');
  var submitLabel = document.getElementById('ppi-submit-label');
  var withdrawBtn = document.getElementById('ppi-withdraw');
  var hintEl = document.getElementById('ppi-hint');
  var hintText = document.getElementById('ppi-hint-text');
  var errorEl = document.getElementById('ppi-error');

  var valueEl = document.getElementById('ppi-value');
  var levelEl = document.getElementById('ppi-level');
  var countEl = document.getElementById('ppi-count');
  var gapEl = document.getElementById('ppi-gap');
  var fillEl = document.getElementById('ppi-fill');

  var RATING_MIN = 1;
  var RATING_MAX = 10;
  var SCALE_MIN = 100;
  var SCALE_MAX = 200;

  var modelScore = parseFloat(block.dataset.modelScore) || SCALE_MIN;

  var myVote = null;      // what the server has recorded for this browser
  var pending = null;     // what the marker is currently proposing, if anything
  var latest = null;      // last aggregate rendered, for repositioning the marker
  var available = block.dataset.available !== 'false';

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
    return WORDS[bandFor(v)] || WORDS[1];
  }

  /* One decimal in the label: two would read as false precision on a gesture,
     but a bare integer would make a free-moving marker look stuck. */
  function ratingText(v) {
    return v.toFixed(1);
  }

  /* Same mapping the server applies to the mean, so the marker can show where a
     rating lands before it is submitted. Duplicated deliberately: a preview is
     not worth a round trip on every pixel of drag. */
  function ratingToIndex(v) {
    var fraction = (v - RATING_MIN) / (RATING_MAX - RATING_MIN);
    return SCALE_MIN + fraction * (SCALE_MAX - SCALE_MIN);
  }

  function ratingToPct(v) {
    return ((v - RATING_MIN) / (RATING_MAX - RATING_MIN)) * 100;
  }

  /* The marker moves freely; only the stored precision is bounded, at the two
     decimals the API keeps. Rounding here as well means the value shown while
     dragging is exactly the value that will be recorded. */
  function pctToRating(pct) {
    var v = RATING_MIN + (pct / 100) * (RATING_MAX - RATING_MIN);
    return quantize(v);
  }

  function quantize(v) {
    return Math.min(RATING_MAX, Math.max(RATING_MIN, Math.round(v * 100) / 100));
  }

  /* Wording is per decile — a rating is a point on a continuum, but the phrase
     attached to it can only come from ten. */
  function bandFor(v) {
    return Math.min(RATING_MAX, Math.max(RATING_MIN, Math.round(v)));
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

  /* --- Requests --------------------------------------------------------- */

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

  /* --- Rendering -------------------------------------------------------- */

  var bubble = null;

  function showBubble(v) {
    if (!bubble) {
      bubble = document.createElement('div');
      bubble.className = 'ppi-bubble';
      bubble.setAttribute('aria-hidden', 'true');
      meterEl.appendChild(bubble);
    }
    bubble.innerHTML = '';
    var num = document.createElement('strong');
    num.textContent = ratingText(v);
    var word = document.createElement('span');
    word.textContent = wordFor(v);
    var mapped = document.createElement('span');
    mapped.className = 'ppi-bubble-mapped';
    mapped.textContent = ratingToIndex(v).toFixed(1);
    bubble.appendChild(num);
    bubble.appendChild(word);
    bubble.appendChild(mapped);
    bubble.style.left = ratingToPct(v) + '%';
  }

  function hideBubble() {
    if (bubble && bubble.parentNode) bubble.parentNode.removeChild(bubble);
    bubble = null;
  }

  /* The marker means the crowd figure at rest and the reader's own proposal
     while one is staged; everything about its position and wording follows
     from which of those two it currently is. */
  function positionPointer() {
    if (pending !== null) {
      pointerEl.style.left = ratingToPct(pending) + '%';
      pointerEl.classList.add('is-pending');
      pointerEl.classList.remove('is-empty');
      pointerEl.setAttribute('aria-valuenow', pending);
      pointerEl.setAttribute(
        'aria-valuetext',
        ratingText(pending) + ' — ' + wordFor(pending) + ', ' +
        ratingToIndex(pending).toFixed(1) + ' on the index'
      );
      showBubble(pending);
      return;
    }

    pointerEl.classList.remove('is-pending');
    hideBubble();

    var pct = latest && latest.scale_pct !== null && latest.scale_pct !== undefined
      ? latest.scale_pct
      : 50;
    pointerEl.style.left = pct + '%';
    pointerEl.classList.toggle(
      'is-empty',
      !(latest && latest.index !== null && latest.index !== undefined)
    );
    pointerEl.setAttribute('aria-valuenow', myVote === null ? 5 : myVote);
    pointerEl.setAttribute(
      'aria-valuetext',
      myVote === null
        ? 'Your read is not cast yet — drag to choose anywhere from 1 to 10'
        : 'Your read: ' + ratingText(myVote) + ' — ' + wordFor(myVote)
    );
  }

  function updateControls() {
    var stagedChange = pending !== null && pending !== myVote;

    submitLabel.textContent = myVote === null ? 'Cast your read' : 'Update your read';
    submitBtn.disabled = !available || !stagedChange;
    withdrawBtn.hidden = myVote === null;

    hintEl.classList.toggle('is-pending', stagedChange);

    if (!available) {
      hintText.textContent = 'Voting is temporarily unavailable.';
    } else if (stagedChange) {
      hintText.innerHTML =
        'Your read: <strong>' + ratingText(pending) + ' · ' + wordFor(pending) +
        '</strong> (' + ratingToIndex(pending).toFixed(1) +
        ' on the index). Press <strong>' + submitLabel.textContent +
        '</strong> to record it.';
    } else if (myVote !== null) {
      hintText.innerHTML =
        'You voted <strong>' + ratingText(myVote) + ' · ' + wordFor(myVote) +
        '</strong>. Drag the marker to change it.';
    } else {
      hintText.innerHTML =
        'Drag the marker to where you think this week sits, then press ' +
        '<strong>Cast your read</strong>.';
    }
  }

  function render(data) {
    if (data._seq && data._seq < rendered) return;
    rendered = data._seq || rendered;
    latest = data;

    myVote = typeof data.your_vote === 'number' ? data.your_vote : null;
    if (typeof data.available === 'boolean') available = data.available;

    if (data.index === null || data.index === undefined) {
      valueEl.textContent = '—';
      levelEl.hidden = true;
      gapEl.hidden = true;
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

    positionPointer();
    updateControls();
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = false;
  }

  function busy(state) {
    submitBtn.disabled = state || submitBtn.disabled;
    withdrawBtn.disabled = state;
    if (state) submitLabel.textContent = 'Saving…';
  }

  function track(name, params) {
    if (typeof window.gtag === 'function') window.gtag('event', name, params || {});
  }

  /* --- Dragging --------------------------------------------------------- */

  function setPending(v) {
    if (v === pending) return;
    pending = v;
    positionPointer();
    updateControls();
  }

  function ratingFromEvent(e) {
    var rect = meterEl.getBoundingClientRect();
    if (!rect.width) return pending === null ? 5 : pending;
    var pct = ((e.clientX - rect.left) / rect.width) * 100;
    return pctToRating(pct);
  }

  var dragging = false;

  /* Pressing anywhere on the track counts, not just on the 16px of marker:
     aiming at the dot is fussy, and the intent of a press on the bar is
     unambiguous. */
  meterEl.addEventListener('pointerdown', function (e) {
    if (!available) return;
    dragging = true;
    pointerEl.classList.add('is-dragging');
    setPending(ratingFromEvent(e));
    /* Capture on the track, so a drag that leaves the bar vertically — which is
       most of them on touch — keeps steering instead of dying. */
    if (meterEl.setPointerCapture) meterEl.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  meterEl.addEventListener('pointermove', function (e) {
    if (!dragging) return;
    setPending(ratingFromEvent(e));
  });

  function endDrag(e) {
    if (!dragging) return;
    dragging = false;
    pointerEl.classList.remove('is-dragging');
    if (e && e.pointerId !== undefined && meterEl.releasePointerCapture) {
      try { meterEl.releasePointerCapture(e.pointerId); } catch (err) { /* already gone */ }
    }
    if (pending !== null) track('ppi_marker_dragged', { value: pending });
  }

  meterEl.addEventListener('pointerup', endDrag);
  meterEl.addEventListener('pointercancel', endDrag);

  pointerEl.addEventListener('keydown', function (e) {
    if (!available) return;
    var current = pending !== null ? pending : (myVote !== null ? myVote : 5);
    /* A tenth per arrow press: fine enough to reach anything the drag can, and
       Page keys give whole points for crossing the scale quickly. */
    var step = 0.1;
    var next = null;
    if (e.key === 'ArrowRight' || e.key === 'ArrowUp') next = current + step;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowDown') next = current - step;
    else if (e.key === 'PageUp') next = current + 1;
    else if (e.key === 'PageDown') next = current - 1;
    else if (e.key === 'Home') next = RATING_MIN;
    else if (e.key === 'End') next = RATING_MAX;
    else if (e.key === 'Enter' || e.key === ' ') {
      if (!submitBtn.disabled) submitBtn.click();
      e.preventDefault();
      return;
    } else return;

    setPending(quantize(next));
    e.preventDefault();
  });

  /* --- Submit / withdraw ------------------------------------------------ */

  submitBtn.addEventListener('click', function () {
    if (pending === null) return;
    errorEl.hidden = true;
    var value = pending;
    var isEdit = myVote !== null;
    var previousValue = myVote;
    busy(true);
    request('POST', { value: value })
      .then(function (data) {
        pending = null; // recorded now: the marker goes back to showing the crowd
        render(data);
        if (isEdit) {
          track('ppi_vote_edited', { value: value, previous_value: previousValue, page_path: location.pathname });
        } else {
          track('ppi_vote_done', { value: value, page_path: location.pathname });
        }
        track('ppi_vote', { value: value, is_edit: isEdit, action: isEdit ? 'edited' : 'done', page_path: location.pathname });
      })
      .catch(function (err) {
        showError(err.message);
      })
      .then(function () {
        withdrawBtn.disabled = false;
        updateControls();
      });
  });

  withdrawBtn.addEventListener('click', function () {
    errorEl.hidden = true;
    busy(true);
    request('DELETE')
      .then(function (data) {
        clearToken();
        data.your_vote = null;
        pending = null;
        render(data);
        track('ppi_withdraw');
      })
      .catch(function (err) {
        showError(err.message);
      })
      .then(function () {
        withdrawBtn.disabled = false;
        updateControls();
      });
  });

  /* The page is CDN-cached, so the server-rendered figures can be up to half an
     hour stale and never know about this browser's own vote. Refresh from the
     no-store endpoint on load. A staged drag survives that refresh: it is the
     reader's input, and the aggregate landing has no bearing on it. */
  updateControls();
  request('GET').then(render).catch(function () { /* keep the rendered fallback */ });
})();
