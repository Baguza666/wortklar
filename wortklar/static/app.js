/**
 * Wortklar - Frontend Application Logic
 * Implements the 4-letter suggestion rule, keyboard navigation,
 * stale request cancellation, safe DOM rendering, and accessible state management.
 */

(function () {
  'use strict';

  // DOM Elements
  const searchForm = document.getElementById('search-form');
  const searchInput = document.getElementById('search-input');
  const searchBtn = document.getElementById('search-btn');
  const suggestionList = document.getElementById('suggestion-list');
  const statusContainer = document.getElementById('status-container');
  const dynamicContent = document.getElementById('dynamic-content');
  const firstUseView = document.getElementById('first-use-view');

  // State
  let activeSuggestionIndex = -1;
  let currentSuggestions = [];
  let suggestDebounceTimer = null;
  let suggestAbortController = null;
  let latestSuggestRequestId = 0;

  /**
   * Normalize input string to Unicode NFC and trim.
   */
  function normalizeInput(str) {
    if (!str) return '';
    return str.normalize('NFC').trim();
  }

  /**
   * Count alphabetical letters in string according to Unicode.
   */
  function countLetters(str) {
    if (!str) return 0;
    // Matches any Unicode letter
    const matches = str.match(/\p{L}/gu);
    return matches ? matches.length : 0;
  }

  /**
   * Safe text element creation (prevents XSS/HTML injection).
   */
  function el(tag, className, textContent) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (textContent !== undefined && textContent !== null) element.textContent = textContent;
    return element;
  }

  /**
   * Retrieve CSRF token from page meta tag if present.
   */
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  /**
   * Check app and database status on load.
   */
  async function checkInitialStatus() {
    try {
      const resp = await fetch('/api/status');
      const data = await resp.json();
      if (data.status === 'missing_index') {
        showIndexMissingState(data.message || 'Database not initialized.');
      }
    } catch (err) {
      // Offline or network error
      console.warn('Status check note:', err.message);
    }
  }

  /**
   * Trigger keyboard suggestions if >= 4 letters typed.
   */
  function handleInput(event) {
    clearTimeout(suggestDebounceTimer);
    const rawVal = searchInput.value;
    const normVal = normalizeInput(rawVal);
    const letters = countLetters(normVal);

    // Rule R2: Show list strictly after fourth typed letter.
    // No suggestion request or list for shorter input.
    if (letters < 4) {
      closeSuggestionList();
      if (suggestAbortController) {
        suggestAbortController.abort();
      }
      return;
    }

    suggestDebounceTimer = setTimeout(() => {
      fetchSuggestions(normVal);
    }, 120); // 120ms debounce
  }

  /**
   * Fetch suggestions with stale response cancellation.
   */
  async function fetchSuggestions(query) {
    if (suggestAbortController) {
      suggestAbortController.abort();
    }
    suggestAbortController = new AbortController();
    const requestId = ++latestSuggestRequestId;

    try {
      const url = `/api/suggest?q=${encodeURIComponent(query)}`;
      const resp = await fetch(url, { signal: suggestAbortController.signal });
      if (resp.status === 401) {
        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search);
        return;
      }
      if (!resp.ok) return;
      const data = await resp.json();

      // Guard against stale response
      if (requestId !== latestSuggestRequestId) {
        return;
      }

      if (data.threshold_met && Array.isArray(data.suggestions) && data.suggestions.length > 0) {
        renderSuggestions(data.suggestions);
      } else {
        closeSuggestionList();
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        console.warn('Suggest error:', err);
      }
    }
  }

  /**
   * Render suggestions into dropdown without modifying search input.
   */
  function renderSuggestions(suggestions) {
    currentSuggestions = suggestions;
    activeSuggestionIndex = -1;
    suggestionList.innerHTML = '';

    suggestions.forEach((item, index) => {
      const li = el('li', 'suggestion-item');
      li.id = `suggestion-item-${index}`;
      li.setAttribute('role', 'option');
      li.setAttribute('aria-selected', 'false');

      const titleDiv = el('div', 'suggestion-title');
      const wordSpan = el('span', 'suggestion-word', item.display);
      titleDiv.appendChild(wordSpan);

      if (item.pos) {
        const badge = el('span', `suggestion-badge ${item.match_type}`, item.pos);
        titleDiv.appendChild(badge);
      }

      li.appendChild(titleDiv);

      if (item.preview) {
        const prevDiv = el('div', 'suggestion-preview', item.preview);
        li.appendChild(prevDiv);
      }

      li.addEventListener('click', () => {
        selectSuggestion(index);
      });

      suggestionList.appendChild(li);
    });

    suggestionList.classList.remove('hidden');
    searchInput.setAttribute('aria-expanded', 'true');
  }

  /**
   * Close and clear suggestion list.
   */
  function closeSuggestionList() {
    suggestionList.innerHTML = '';
    suggestionList.classList.add('hidden');
    searchInput.setAttribute('aria-expanded', 'false');
    searchInput.removeAttribute('aria-activedescendant');
    currentSuggestions = [];
    activeSuggestionIndex = -1;
  }

  /**
   * Keyboard navigation inside the suggestion dropdown.
   */
  function handleKeyDown(event) {
    const isListOpen = !suggestionList.classList.contains('hidden') && currentSuggestions.length > 0;

    switch (event.key) {
      case 'ArrowDown':
        if (isListOpen) {
          event.preventDefault();
          navigateSuggestions(1);
        }
        break;

      case 'ArrowUp':
        if (isListOpen) {
          event.preventDefault();
          navigateSuggestions(-1);
        }
        break;

      case 'Enter':
        // If a row is highlighted, choose it. Otherwise submit typed query.
        if (isListOpen && activeSuggestionIndex >= 0 && activeSuggestionIndex < currentSuggestions.length) {
          event.preventDefault();
          selectSuggestion(activeSuggestionIndex);
        } else {
          event.preventDefault();
          submitLookup();
        }
        break;

      case 'Escape':
        if (isListOpen) {
          event.preventDefault();
          closeSuggestionList();
        }
        break;
    }
  }

  /**
   * Cycle selection through list with Arrow keys.
   */
  function navigateSuggestions(delta) {
    const count = currentSuggestions.length;
    if (count === 0) return;

    if (activeSuggestionIndex >= 0) {
      const prevEl = document.getElementById(`suggestion-item-${activeSuggestionIndex}`);
      if (prevEl) {
        prevEl.classList.remove('selected');
        prevEl.setAttribute('aria-selected', 'false');
      }
    }

    activeSuggestionIndex += delta;
    if (activeSuggestionIndex >= count) {
      activeSuggestionIndex = 0;
    } else if (activeSuggestionIndex < 0) {
      activeSuggestionIndex = count - 1;
    }

    const nextEl = document.getElementById(`suggestion-item-${activeSuggestionIndex}`);
    if (nextEl) {
      nextEl.classList.add('selected');
      nextEl.setAttribute('aria-selected', 'true');
      nextEl.scrollIntoView({ block: 'nearest' });
      searchInput.setAttribute('aria-activedescendant', nextEl.id);
    }
  }

  /**
   * User explicitly chose a suggestion.
   */
  function selectSuggestion(index) {
    const item = currentSuggestions[index];
    if (!item) return;

    // Use target_word or term
    const chosenWord = item.target_word || item.term;
    searchInput.value = chosenWord;
    closeSuggestionList();
    executeLookup(chosenWord);
  }

  /**
   * Form submission (explicit Enter or Search button).
   */
  function submitLookup() {
    closeSuggestionList();
    const query = normalizeInput(searchInput.value);
    if (!query) return;
    executeLookup(query);
  }

  /**
   * Execute lookup for complete word of any length.
   */
  async function executeLookup(query) {
    if (!query) return;
    closeSuggestionList();
    clearStatus();

    // Update URL hash without reload for easy bookmarking/sharing
    window.location.hash = encodeURIComponent(query);

    dynamicContent.innerHTML = '';
    firstUseView.style.display = 'none';

    // Loading indicator
    const loadingCard = el('div', 'state-card', 'Searching Wortklar dictionary...');
    dynamicContent.appendChild(loadingCard);

    try {
      const resp = await fetch(`/api/lookup?q=${encodeURIComponent(query)}`);
      if (resp.status === 401) {
        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search);
        return;
      }
      const data = await resp.json();

      dynamicContent.innerHTML = '';

      if (resp.status === 503 && data.error === 'database_missing') {
        showIndexMissingState(data.message);
        return;
      }

      if (!resp.ok) {
        showAppErrorState(data.message || 'Lookup failed.', query);
        return;
      }

      renderLookupResults(data, query);
    } catch (err) {
      dynamicContent.innerHTML = '';
      showAppErrorState(`Connection error: ${err.message}. Please check if the local server is running.`, query);
    }
  }

  /**
   * Render complete lookup results according to R2 and R3.
   */
  function renderLookupResults(data, query) {
    const hasExact = data.exact_entries && data.exact_entries.length > 0;
    const hasForms = data.form_matches && data.form_matches.length > 0;
    const hasLookalikes = data.lookalikes && data.lookalikes.length > 0;
    const didYouMean = data.did_you_mean;

    // Case 1: No match at all and no suggestion
    if (!hasExact && !hasForms && !didYouMean) {
      showNoMatchState(query);
      return;
    }

    // Case 2: Did You Mean banner (when no exact entries exist, but a candidate exists)
    if (!hasExact && didYouMean) {
      const dymBanner = el('div', 'assistance-banner');
      const dymTitle = el('div', 'assistance-title', 'Did you mean:');
      dymBanner.appendChild(dymTitle);

      const itemP = el('p', 'assistance-item');
      const targetLink = el('span', 'assistance-target', didYouMean.display);
      targetLink.addEventListener('click', () => {
        searchInput.value = didYouMean.target_word || didYouMean.term;
        executeLookup(didYouMean.target_word || didYouMean.term);
      });
      itemP.appendChild(targetLink);

      if (didYouMean.preview) {
        itemP.appendChild(document.createTextNode(` — ${didYouMean.preview}`));
      }
      if (didYouMean.note) {
        const noteSpan = el('span', 'assistance-note', `(${didYouMean.note})`);
        itemP.appendChild(noteSpan);
      }
      dymBanner.appendChild(itemP);
      dynamicContent.appendChild(dymBanner);
    }

    // Case 3: Form relationship banner (e.g. Häuser → Haus, ging → gehen)
    if (hasForms) {
      const formBanner = el('div', 'form-banner');
      const formLabels = data.form_matches.map(f => {
        let label = `${f.form_label}`;
        if (f.tag_label) label += ` (${f.tag_label})`;
        return label;
      }).join('; ');
      formBanner.innerHTML = `<strong>Inflected form match:</strong> ${escapeHtml(formLabels)}`;
      dynamicContent.appendChild(formBanner);
    }

    // Case 4: Lookalikes banner when exact match exists (schon vs schön, Masse vs Maße, Hauser vs Häuser)
    if (hasExact && hasLookalikes) {
      const lookBanner = el('div', 'assistance-banner');
      const lookTitle = el('div', 'assistance-title', 'Attested lookalikes & spelling alternatives:');
      lookBanner.appendChild(lookTitle);

      const listUl = el('ul', 'assistance-list');
      data.lookalikes.forEach(item => {
        const li = el('li', 'assistance-item');
        const targetLink = el('span', 'assistance-target', item.display);
        targetLink.addEventListener('click', () => {
          searchInput.value = item.target_word || item.term;
          executeLookup(item.target_word || item.term);
        });
        li.appendChild(targetLink);
        if (item.preview) {
          li.appendChild(document.createTextNode(` — ${item.preview}`));
        }
        if (item.note) {
          const noteSpan = el('span', 'assistance-note', `(${item.note})`);
          li.appendChild(noteSpan);
        }
        listUl.appendChild(li);
      });
      lookBanner.appendChild(listUl);
      dynamicContent.appendChild(lookBanner);
    }

    // Case 5: Render entry cards
    if (hasExact) {
      data.exact_entries.forEach(entry => {
        renderEntryCard(entry);
      });
    }
  }

  /**
   * Render individual Entry Card with A1 core forms, senses, examples, and detailed grammar disclosure.
   */
  function renderEntryCard(entry) {
    const card = el('article', 'entry-card');

    // Header
    const header = el('div', 'entry-header');
    const titleRow = el('div', 'entry-title-row');

    if (entry.article && entry.part_of_speech === 'noun') {
      const artSpan = el('span', 'entry-article', `${entry.article} `);
      titleRow.appendChild(artSpan);
    }

    const headwordH2 = el('h2', 'entry-headword', entry.headword);
    titleRow.appendChild(headwordH2);

    const posBadge = el('span', `entry-pos-badge ${entry.part_of_speech}`, entry.part_of_speech);
    titleRow.appendChild(posBadge);

    if (entry.source_edition) {
      const srcText = entry.source_edition === 'both' ? 'English & German Wiktionary' :
                      (entry.source_edition === 'de' ? 'German Wiktionary' : 'English Wiktionary');
      const srcBadge = el('span', 'entry-source-badge', srcText);
      titleRow.appendChild(srcBadge);
    }

    header.appendChild(titleRow);
    card.appendChild(header);

    // Core Learner Forms Box (R3 Default View)
    const grammar = entry.grammar || {};
    const coreBox = el('div', 'core-forms-box');
    let hasCoreForms = false;

    if (entry.part_of_speech === 'noun') {
      hasCoreForms = true;
      // Singular with article
      const sgRow = el('div', 'core-form-item');
      sgRow.appendChild(el('span', 'core-form-label', 'Nominative Singular:'));
      sgRow.appendChild(el('span', 'core-form-val', grammar.nominative_singular || entry.headword));
      coreBox.appendChild(sgRow);

      // Plural status and form
      const plRow = el('div', 'core-form-item');
      plRow.appendChild(el('span', 'core-form-label', 'Nominative Plural:'));
      let plVal = 'form unavailable';
      if (grammar.plural_status === 'no_plural') {
        plVal = 'no plural';
      } else if (grammar.plural_status === 'plural_only') {
        plVal = 'plural only';
      } else if (grammar.nominative_plural) {
        plVal = grammar.nominative_plural;
      }
      plRow.appendChild(el('span', 'core-form-val', plVal));
      coreBox.appendChild(plRow);

      if (grammar.gender) {
        const genRow = el('div', 'core-form-item');
        genRow.appendChild(el('span', 'core-form-label', 'Gender:'));
        genRow.appendChild(el('span', 'core-form-val', grammar.gender));
        coreBox.appendChild(genRow);
      }
    } else if (entry.part_of_speech === 'verb') {
      hasCoreForms = true;
      // Present 3sg
      const presRow = el('div', 'core-form-item');
      presRow.appendChild(el('span', 'core-form-label', 'Present (er/sie/es):'));
      presRow.appendChild(el('span', 'core-form-val', grammar.present_3sg || '—'));
      coreBox.appendChild(presRow);

      // Simple past (Präteritum)
      const pastRow = el('div', 'core-form-item');
      pastRow.appendChild(el('span', 'core-form-label', 'Simple Past (Präteritum):'));
      pastRow.appendChild(el('span', 'core-form-val', grammar.simple_past || '—'));
      coreBox.appendChild(pastRow);

      // Past participle (Partizip II)
      const partRow = el('div', 'core-form-item');
      partRow.appendChild(el('span', 'core-form-label', 'Past Participle (Partizip II):'));
      partRow.appendChild(el('span', 'core-form-val', grammar.past_participle || '—'));
      coreBox.appendChild(partRow);

      // Auxiliary
      if (grammar.auxiliary) {
        const auxRow = el('div', 'core-form-item');
        auxRow.appendChild(el('span', 'core-form-label', 'Auxiliary:'));
        auxRow.appendChild(el('span', 'core-form-val', grammar.auxiliary));
        coreBox.appendChild(auxRow);
      }
    } else if (entry.part_of_speech === 'adj') {
      if (grammar.has_comparison) {
        hasCoreForms = true;
        const compRow = el('div', 'core-form-item');
        compRow.appendChild(el('span', 'core-form-label', 'Comparative:'));
        compRow.appendChild(el('span', 'core-form-val', grammar.comparative || '—'));
        coreBox.appendChild(compRow);

        const supRow = el('div', 'core-form-item');
        supRow.appendChild(el('span', 'core-form-label', 'Superlative:'));
        supRow.appendChild(el('span', 'core-form-val', grammar.superlative || '—'));
        coreBox.appendChild(supRow);
      }
    }

    if (hasCoreForms) {
      card.appendChild(coreBox);
    }

    // Senses Section
    if (entry.senses && entry.senses.length > 0) {
      const sensesSec = el('div', 'senses-section');
      const sensesTitle = el('h3', 'senses-title', 'English Meanings:');
      sensesSec.appendChild(sensesTitle);

      const ol = el('ol', 'sense-list');
      entry.senses.forEach(s => {
        const li = el('li', 'sense-item');
        const glossEn = el('span', 'sense-gloss-en', s.gloss_en || 'English meaning unavailable');
        li.appendChild(glossEn);

        if (s.tags && s.tags.length > 0) {
          s.tags.forEach(tag => {
            if (tag !== 'table-tags') {
              li.appendChild(el('span', 'sense-tag', tag));
            }
          });
        }

        if (s.gloss_de) {
          const deGloss = el('span', 'sense-gloss-de', `(dt. ${s.gloss_de})`);
          li.appendChild(deGloss);
        }

        ol.appendChild(li);
      });

      sensesSec.appendChild(ol);
      card.appendChild(sensesSec);
    }

    // Bilingual Examples Section
    const allExamples = [];
    if (entry.senses) {
      entry.senses.forEach(s => {
        if (s.examples && s.examples.length > 0) {
          allExamples.push(...s.examples);
        }
      });
    }

    if (allExamples.length > 0) {
      const exSec = el('div', 'examples-section');
      exSec.appendChild(el('h4', 'examples-title', 'Bilingual Example:'));

      allExamples.slice(0, 3).forEach(ex => {
        const exItem = el('div', 'example-item');
        exItem.appendChild(el('div', 'example-de', ex.de));
        exItem.appendChild(el('div', 'example-en', ex.en));
        exSec.appendChild(exItem);
      });

      card.appendChild(exSec);
    }

    // More Grammar Disclosure
    renderMoreGrammarSection(card, entry, grammar);

    // Online Check Action for Existing Result
    const onlineSec = el('div', 'entry-online-action');
    onlineSec.style.marginTop = '12px';
    const checkBtn = el('button', 'btn-online-check-secondary', 'Check Wiktionary for updates/missing forms');
    checkBtn.type = 'button';
    const onlineCardContainer = el('div', 'online-results-container');
    checkBtn.addEventListener('click', () => {
      triggerOnlineCheck(entry.headword, checkBtn, onlineCardContainer);
    });
    onlineSec.appendChild(checkBtn);
    onlineSec.appendChild(onlineCardContainer);
    card.appendChild(onlineSec);

    // Entry Footer: Source Link
    if (entry.source_url) {
      const footer = el('div', 'entry-footer');
      const srcLink = el('a', 'source-link', 'View source on Wiktionary ↗');
      srcLink.href = entry.source_url;
      srcLink.target = '_blank';
      srcLink.rel = 'noopener noreferrer';
      footer.appendChild(srcLink);
      card.appendChild(footer);
    }

    dynamicContent.appendChild(card);
  }

  /**
   * Render semantic tables in the More Grammar disclosure.
   */
  function renderMoreGrammarSection(card, entry, grammar) {
    const pos = entry.part_of_speech;
    let hasDetails = false;

    const details = el('details', 'grammar-details');
    const summary = el('summary', 'grammar-summary', 'More grammar & inflection tables');
    details.appendChild(summary);

    const contentDiv = el('div', 'grammar-content');

    if (pos === 'noun') {
      // 4 Cases Table
      if (grammar.cases && grammar.cases.length > 0) {
        hasDetails = true;
        const scrollWrap = el('div', 'table-scroll-wrapper');
        const table = el('table', 'grammar-table');
        table.appendChild(el('caption', '', `Noun Declension: ${entry.headword}`));

        const thead = el('thead');
        const hRow = el('tr');
        hRow.appendChild(el('th', '', 'Case'));
        hRow.appendChild(el('th', '', 'Singular'));
        hRow.appendChild(el('th', '', 'Plural'));
        thead.appendChild(hRow);
        table.appendChild(thead);

        const tbody = el('tbody');
        grammar.cases.forEach(cRow => {
          const row = el('tr');
          const th = el('th', '', `${cRow.case}`);
          th.title = cRow.description || '';
          row.appendChild(th);
          row.appendChild(el('td', '', cRow.singular || '—'));
          row.appendChild(el('td', '', cRow.plural || '—'));
          tbody.appendChild(row);
        });
        table.appendChild(tbody);
        scrollWrap.appendChild(table);
        contentDiv.appendChild(scrollWrap);
      }

      // Plural variants
      if (grammar.plural_variants && grammar.plural_variants.length > 0) {
        hasDetails = true;
        const plBlock = el('div', 'plural-variants-block');
        plBlock.appendChild(el('strong', '', 'Attested Plural Variants:'));
        const ul = el('ul', 'plural-variants-list');
        grammar.plural_variants.forEach(pv => {
          const li = el('li', '', pv.label ? `${pv.form} (${pv.label})` : pv.form);
          ul.appendChild(li);
        });
        plBlock.appendChild(ul);
        contentDiv.appendChild(plBlock);
      }
    } else if (pos === 'verb') {
      // Conjugation Table
      if (grammar.conjugation_table && grammar.conjugation_table.length > 0) {
        hasDetails = true;
        const scrollWrap = el('div', 'table-scroll-wrapper');
        const table = el('table', 'grammar-table');
        table.appendChild(el('caption', '', `Verb Conjugation: ${entry.headword}`));

        const thead = el('thead');
        const hRow = el('tr');
        hRow.appendChild(el('th', '', 'Person'));
        hRow.appendChild(el('th', '', 'Präsens'));
        hRow.appendChild(el('th', '', 'Präteritum'));
        hRow.appendChild(el('th', '', 'Konjunktiv I'));
        hRow.appendChild(el('th', '', 'Konjunktiv II'));
        thead.appendChild(hRow);
        table.appendChild(thead);

        const tbody = el('tbody');
        grammar.conjugation_table.forEach(pRow => {
          const row = el('tr');
          row.appendChild(el('th', '', pRow.person));
          row.appendChild(el('td', '', pRow.present || '—'));
          row.appendChild(el('td', '', pRow.past || '—'));
          row.appendChild(el('td', '', pRow.subjunctive_i || '—'));
          row.appendChild(el('td', '', pRow.subjunctive_ii || '—'));
          tbody.appendChild(row);
        });
        table.appendChild(tbody);
        scrollWrap.appendChild(table);
        contentDiv.appendChild(scrollWrap);
      }

      // Imperative
      if (grammar.imperative) {
        hasDetails = true;
        const impBlock = el('div', 'imperative-block');
        impBlock.innerHTML = `<strong>Imperative:</strong> du: ${escapeHtml(grammar.imperative.du)} | ihr: ${escapeHtml(grammar.imperative.ihr)} | Sie: ${escapeHtml(grammar.imperative.Sie)}`;
        contentDiv.appendChild(impBlock);
      }
    } else if (pos === 'adj') {
      // Declension Tables
      if (grammar.declensions) {
        Object.keys(grammar.declensions).forEach(dtype => {
          hasDetails = true;
          const declData = grammar.declensions[dtype];
          const scrollWrap = el('div', 'table-scroll-wrapper');
          const table = el('table', 'grammar-table');
          table.appendChild(el('caption', '', declData.label));

          const thead = el('thead');
          const hRow = el('tr');
          hRow.appendChild(el('th', '', 'Case'));
          hRow.appendChild(el('th', '', 'Maskulin'));
          hRow.appendChild(el('th', '', 'Feminin'));
          hRow.appendChild(el('th', '', 'Neutral'));
          hRow.appendChild(el('th', '', 'Plural'));
          thead.appendChild(hRow);
          table.appendChild(thead);

          const tbody = el('tbody');
          declData.rows.forEach(r => {
            const row = el('tr');
            row.appendChild(el('th', '', r.case));
            row.appendChild(el('td', '', r.masculine || '—'));
            row.appendChild(el('td', '', r.feminine || '—'));
            row.appendChild(el('td', '', r.neuter || '—'));
            row.appendChild(el('td', '', r.plural || '—'));
            tbody.appendChild(row);
          });
          table.appendChild(tbody);
          scrollWrap.appendChild(table);
          contentDiv.appendChild(scrollWrap);
        });
      }
    }

    if (hasDetails) {
      details.appendChild(contentDiv);
      card.appendChild(details);
    }
  }

  /**
   * Helper to escape HTML characters in text.
   */
  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  /**
   * Distinct State: No match found.
   */
  function showNoMatchState(query) {
    const card = el('div', 'state-card');
    card.appendChild(el('h2', '', `No entry found for "${query}"`));
    card.appendChild(el('p', '', 'Wortklar could not find an exact lemma, inflected form, or close spelling variant locally.'));

    const ul = el('ul');
    ul.appendChild(el('li', '', 'Check for spelling or capitalization mistakes.'));
    ul.appendChild(el('li', '', 'If searching an inflected form, try the infinitive verb or singular noun.'));
    ul.appendChild(el('li', '', 'Verify umlauts (ä, ö, ü) and ß.'));
    card.appendChild(ul);

    // Online research action for missing entry (R5)
    const actionBox = el('div', 'online-action-box');
    actionBox.appendChild(el('p', '', 'Or search live Wiktionary directly for newly added entries and definitions:'));
    const checkBtn = el('button', 'btn-online-check', `Check Wiktionary Online for "${query}"`);
    checkBtn.id = 'check-wiktionary-btn';
    checkBtn.type = 'button';
    const onlineContainer = el('div', 'online-results-container');
    checkBtn.addEventListener('click', () => {
      triggerOnlineCheck(query, checkBtn, onlineContainer);
    });
    actionBox.appendChild(checkBtn);
    actionBox.appendChild(onlineContainer);
    card.appendChild(actionBox);

    dynamicContent.appendChild(card);
  }

  /**
   * Explicit Check Wiktionary Online action (R5).
   * Keeps local result visible while querying external Wiktionary MediaWiki API.
   */
  async function triggerOnlineCheck(word, button, container) {
    if (!word || !container) return;

    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = 'Checking Wiktionary...';

    container.innerHTML = '';
    const loadingDiv = el('div', 'online-loading', 'Connecting to Wiktionary MediaWiki API...');
    container.appendChild(loadingDiv);

    try {
      const headers = { 'Content-Type': 'application/json' };
      const csrf = getCsrfToken();
      if (csrf) {
        headers['X-CSRF-Token'] = csrf;
      }
      const resp = await fetch('/api/check_online', {
        method: 'POST',
        headers: headers,
        body: JSON.stringify({ word: word, csrf_token: csrf })
      });

      if (resp.status === 401) {
        window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search);
        return;
      }

      const data = await resp.json();
      container.innerHTML = '';

      if (!resp.ok) {
        const errDiv = el('div', 'state-card error', data.message || 'Online check failed.');
        const retryBtn = el('button', 'btn-online-check-secondary', 'Retry');
        retryBtn.addEventListener('click', () => {
          triggerOnlineCheck(word, button, container);
        });
        errDiv.appendChild(retryBtn);
        container.appendChild(errDiv);
        return;
      }

      renderOnlineResults(data, container);
    } catch (err) {
      container.innerHTML = '';
      const errDiv = el('div', 'state-card error', `Network error: ${err.message}. Local search remains fully operational.`);
      container.appendChild(errDiv);
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  }

  /**
   * Render separate "Online dictionary result" card with source and optional AI explanation.
   */
  function renderOnlineResults(data, container) {
    const w = data.wiktionary || {};
    const status = w.status;

    if (status === 'not_found') {
      const card = el('div', 'state-card warning');
      card.appendChild(el('h3', '', `Word "${data.query}" not found on Wiktionary`));
      card.appendChild(el('p', '', 'No matching German page was found on de.wiktionary.org or en.wiktionary.org.'));
      container.appendChild(card);
      return;
    }

    if (status === 'non_german_page') {
      const card = el('div', 'state-card warning');
      card.appendChild(el('h3', '', `Page "${w.title || data.query}" is not in German`));
      card.appendChild(el('p', '', 'A Wiktionary page with this title exists, but it has no German language section.'));
      if (w.source_url) {
        const link = el('a', 'source-link', `View page on Wiktionary (${w.title}) ↗`);
        link.href = w.source_url;
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
        card.appendChild(link);
      }
      container.appendChild(card);
      return;
    }

    // Success: Render Online dictionary result card
    const card = el('div', 'online-result-card');

    // Header
    const cardHeader = el('div', 'online-card-header');
    const badge = el('span', 'online-badge', 'Online dictionary result');
    cardHeader.appendChild(badge);

    const titleRow = el('div', 'entry-title-row');
    const oEntry = w.online_entry || {};

    if (oEntry.article && oEntry.part_of_speech === 'noun') {
      titleRow.appendChild(el('span', 'entry-article', `${oEntry.article} `));
    }
    titleRow.appendChild(el('h3', 'online-headword', oEntry.headword || w.matched_title));
    if (oEntry.part_of_speech) {
      titleRow.appendChild(el('span', 'entry-pos-badge', oEntry.part_of_speech));
    }
    cardHeader.appendChild(titleRow);
    card.appendChild(cardHeader);

    // Core mapped fields
    if (oEntry.part_of_speech === 'noun' && (oEntry.plural || oEntry.gender)) {
      const coreBox = el('div', 'core-forms-box');
      if (oEntry.article && oEntry.headword) {
        const sg = el('div', 'core-form-item');
        sg.appendChild(el('span', 'core-form-label', 'Singular:'));
        sg.appendChild(el('span', 'core-form-val', `${oEntry.article} ${oEntry.headword}`));
        coreBox.appendChild(sg);
      }
      if (oEntry.plural) {
        const pl = el('div', 'core-form-item');
        pl.appendChild(el('span', 'core-form-label', 'Plural:'));
        pl.appendChild(el('span', 'core-form-val', oEntry.plural));
        coreBox.appendChild(pl);
      }
      card.appendChild(coreBox);
    }

    // Meanings from Wiktionary
    if (oEntry.meanings && oEntry.meanings.length > 0) {
      const sensesSec = el('div', 'senses-section');
      sensesSec.appendChild(el('h4', 'senses-title', 'Definitions (Wiktionary):'));
      const ol = el('ol', 'sense-list');
      oEntry.meanings.forEach(m => {
        ol.appendChild(el('li', 'sense-item', m));
      });
      sensesSec.appendChild(ol);
      card.appendChild(sensesSec);
    }

    // AI-assisted explanation (if Gemini was enabled and returned data)
    if (data.ai_explanation) {
      const ai = data.ai_explanation;
      const aiBox = el('div', 'ai-explanation-box');
      const aiHeader = el('div', 'ai-header');
      aiHeader.appendChild(el('span', 'ai-badge', 'AI-assisted explanation'));
      aiBox.appendChild(aiHeader);

      const aiTextP = el('p', 'ai-text', ai.english_explanation);
      if (ai.evidence_ids && ai.evidence_ids.length > 0) {
        ai.evidence_ids.forEach(id => {
          aiTextP.appendChild(el('span', 'ai-evidence-cite', `[Evidence #${id}]`));
        });
      }
      aiBox.appendChild(aiTextP);

      if (ai.learner_note) {
        aiBox.appendChild(el('p', 'ai-note', `Learner note: ${ai.learner_note}`));
      }

      card.appendChild(aiBox);
    } else if (data.ai_status === 'gemini_disabled') {
      const note = el('p', 'assistance-note', '(Gemini AI stage not configured; showing verified Wiktionary facts.)');
      note.style.margin = '8px 0';
      card.appendChild(note);
    }

    // Numbered evidence records disclosure
    if (w.evidence && w.evidence.length > 0) {
      const evDetails = el('details', 'evidence-details');
      evDetails.appendChild(el('summary', 'evidence-summary', `Wiktionary evidence records (${w.evidence.length})`));

      const evList = el('ul', 'evidence-list');
      w.evidence.forEach(item => {
        const li = el('li', 'evidence-item');
        li.appendChild(el('span', 'evidence-id-tag', `[Evidence #${item.id}]`));
        li.appendChild(document.createTextNode(item.text));
        evList.appendChild(li);
      });
      evDetails.appendChild(evList);
      card.appendChild(evDetails);
    }

    // Source link with revision id
    if (w.source_url) {
      const footer = el('div', 'entry-footer');
      const srcText = w.revid ? `View on ${w.source_edition || 'Wiktionary'} (rev ${w.revid}) ↗` : 'View on Wiktionary ↗';
      const link = el('a', 'source-link', srcText);
      link.href = w.source_url;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      footer.appendChild(link);
      card.appendChild(footer);
    }

    container.appendChild(card);
  }

  /**
   * Distinct State: Missing index / database.
   */
  function showIndexMissingState(message) {
    clearStatus();
    const alertDiv = el('div', 'state-card warning');
    alertDiv.appendChild(el('h2', '', 'Dictionary Database Not Initialized'));
    alertDiv.appendChild(el('p', '', message || 'The local SQLite database has not been initialized yet.'));

    const codeP = el('p', '', 'To download real Wiktionary data and build the database, run:');
    const kbd = el('kbd', '', 'python3 bootstrap.py');
    codeP.appendChild(document.createElement('br'));
    codeP.appendChild(kbd);
    alertDiv.appendChild(codeP);

    statusContainer.appendChild(alertDiv);
  }

  /**
   * Distinct State: Application / server error.
   */
  function showAppErrorState(message, query) {
    const card = el('div', 'state-card error');
    card.appendChild(el('h2', '', 'Application Error'));
    card.appendChild(el('p', '', message));

    const retryBtn = el('button', 'search-btn', 'Try Again');
    retryBtn.style.marginTop = '12px';
    retryBtn.addEventListener('click', () => {
      executeLookup(query);
    });
    card.appendChild(retryBtn);

    dynamicContent.appendChild(card);
  }

  function clearStatus() {
    statusContainer.innerHTML = '';
  }

  // Event Listeners
  searchInput.addEventListener('input', handleInput);
  searchInput.addEventListener('keydown', handleKeyDown);
  searchBtn.addEventListener('click', submitLookup);
  searchForm.addEventListener('submit', (e) => {
    e.preventDefault();
    submitLookup();
  });

  // Close suggestion list on click outside
  document.addEventListener('click', (e) => {
    if (!searchForm.contains(e.target)) {
      closeSuggestionList();
    }
  });

  // Example links in first use view
  document.querySelectorAll('.example-link').forEach(link => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const href = link.getAttribute('href');
      const term = href.replace('#', '');
      searchInput.value = term;
      executeLookup(term);
    });
  });

  // Initial load hash check
  window.addEventListener('load', () => {
    checkInitialStatus();
    if (window.location.hash) {
      const term = decodeURIComponent(window.location.hash.substring(1));
      if (term) {
        searchInput.value = term;
        executeLookup(term);
      }
    }
  });

})();

