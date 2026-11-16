(() => {
  const EXAMS = JSON.parse(document.getElementById("exams-data")?.textContent || "{}");
  const GROUP_LANGS = JSON.parse(document.getElementById("groups-data")?.textContent || "{}");
  const groupSelect = document.getElementById("test-group");

  const profile = () => EXAMS[GROUP_LANGS[groupSelect?.value] || "en"] || EXAMS.en;

  const typeButtons = () => {
    const exam = profile();
    const tf = exam.tfng.map((item) => item[1]).join(" / ");
    const yn = exam.ynng.map((item) => item[1]).join(" / ");
    return [
      { id: "fill_blank", label: "Notes / Form", hint: "пропуски {1} {2} как в буклете" },
      { id: "short", label: "Предложения", hint: "sentence completion" },
      { id: "single", label: "Выбор A/B/C", hint: "один верный" },
      { id: "multiple", label: "Несколько ответов", hint: "pick N" },
      { id: "tfng", label: tf },
      { id: "ynng", label: yn },
      { id: "match", label: "Соответствия", hint: "банк вариантов" },
      { id: "heading", label: "Заголовки", hint: "paragraph headings" },
      { id: "text", label: "Развёрнутый ответ" },
    ];
  };

  const uid = (prefix) => `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

  const defaultNotesBody = () =>
    `${profile().exam === "ТРКИ" ? "Форма записи" : "Booking form"}\n\n## Details\n* Name: {1}\n* Date: {2}\n* Place: {3}\n`;

  const defaultInstructions = (type) => {
    const exam = profile();
    if (type === "fill_blank") return exam.notes_instruction || "Complete the notes below.\nWrite ONE WORD AND/OR A NUMBER for each answer.";
    if (type === "tfng") return exam.tfng.map((item) => item[1]).join(" / ");
    if (type === "ynng") return exam.ynng.map((item) => item[1]).join(" / ");
    if (type === "short") return "Complete the sentences. Write NO MORE THAN TWO WORDS AND/OR A NUMBER for each answer.";
    if (type === "single") return "Choose the correct letter, A, B or C.";
    if (type === "heading") return "Choose the correct heading for each paragraph.";
    if (type === "match") return "Match each item with the correct letter.";
    return exam.instruction || "";
  };

  const emptyGroup = (sectionId, type) => {
    const exam = profile();
    const group = {
      id: uid("q"),
      db_id: null,
      sectionId,
      type,
      text: defaultInstructions(type),
      intro: "",
      title: "",
      body: type === "fill_blank" ? defaultNotesBody() : "",
      answers: "",
      points: 1,
      options: ["", "", ""],
      correct: type === "multiple" ? [] : "",
      left: [`${exam.paragraph} A`, `${exam.paragraph} B`],
      right: ["i", "ii", "iii"],
      items: [],
    };
    if (type === "tfng" || type === "ynng") {
      group.items = [
        { stmt: "", correct: "" },
        { stmt: "", correct: "" },
        { stmt: "", correct: "" },
      ];
    }
    if (type === "short") {
      group.items = [
        { prompt: "", correct: "" },
        { prompt: "", correct: "" },
      ];
    }
    if (type === "single") {
      group.items = [
        { stem: "", options: ["", "", ""], correct: "" },
        { stem: "", options: ["", "", ""], correct: "" },
      ];
    }
    return group;
  };

  const defaultSections = (kind) => {
    const exam = profile();
    if (kind === "listening") {
      return Array.from({ length: exam.listening_count }, (_, index) => ({
        id: uid("s"),
        db_id: null,
        title: exam.listening_title.replace("{}", String(index + 1)),
        kind: "audio",
        body: "",
        audio_url: "",
      }));
    }
    if (kind === "reading") {
      return Array.from({ length: exam.reading_count }, (_, index) => ({
        id: uid("s"),
        db_id: null,
        title: exam.reading_title.replace("{}", String(index + 1)),
        kind: "passage",
        body: "",
        audio_url: "",
      }));
    }
    return [{ id: uid("s"), db_id: null, title: "Задания", kind: "passage", body: "", audio_url: "" }];
  };

  const source = JSON.parse(document.getElementById("builder-data").textContent || "{}");
  const kindSelect = document.getElementById("test-kind");
  const state = {
    kind: source.kind || kindSelect?.value || "reading",
    sections: source.sections?.length ? source.sections : defaultSections(source.kind || "reading"),
    questions: source.questions || [],
    active: null,
  };
  state.active = state.sections[0]?.id;

  const el = {
    tabs: document.getElementById("section-tabs"),
    section: document.getElementById("section-editor"),
    questions: document.getElementById("questions-editor"),
    types: document.getElementById("type-grid"),
    hint: document.getElementById("builder-hint"),
    json: document.getElementById("builder-json"),
    audio: document.getElementById("audio-slot"),
    form: document.getElementById("builder-form"),
  };

  const activeSection = () => state.sections.find((item) => item.id === state.active) || state.sections[0];
  const sectionQuestions = () => state.questions.filter((item) => item.sectionId === state.active);

  const spanOf = (question) => {
    if (question.type === "fill_blank" && question.body) {
      const nums = [...String(question.body).matchAll(/\{(\d+)\}/g)].map((match) => Number(match[1]));
      const unique = [...new Set(nums)];
      return unique.length || 1;
    }
    if (["fill_blank", "short", "tfng", "ynng", "single"].includes(question.type) && question.items?.length) {
      return question.items.length;
    }
    if (question.type === "match" || question.type === "heading") {
      return (question.left || []).filter(Boolean).length || 1;
    }
    return 1;
  };

  const rangeOf = (question) => {
    let cursor = 1;
    for (const item of state.questions) {
      const span = spanOf(item);
      if (item.id === question.id) return [cursor, cursor + span - 1];
      cursor += span;
    }
    return [1, 1];
  };

  function escapeHtml(value) {
    return String(value || "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
  }
  function escapeAttr(value) {
    return escapeHtml(value).replaceAll('"', "&quot;");
  }

  function notesPreview(body) {
    return String(body || "")
      .split("\n")
      .map((line) => {
        if (!line.trim()) return "";
        if (line.trim().startsWith("##")) return `<div class="nb-section">${escapeHtml(line.replace(/^##\s*/, ""))}</div>`;
        const bullet = line.trim().startsWith("*");
        const cleaned = line.replace(/^\s*\*\s*/, "");
        const html = escapeHtml(cleaned).replace(/\{(\d+)\}/g, (_, num) => `<span class="nb-num">${num}</span><span class="nb-input nb-ghost"></span>`);
        return `<div class="nb-line ${bullet ? "nb-bullet" : ""}">${html}</div>`;
      })
      .join("");
  }

  function render() {
    const exam = profile();
    const examLabel = document.getElementById("exam-label");
    if (examLabel) {
      examLabel.textContent = `${exam.exam} · ${
        state.kind === "listening" ? exam.listening_name : state.kind === "reading" ? exam.reading_name : "общий тест"
      }`;
    }
    if (kindSelect && kindSelect.value !== state.kind) kindSelect.value = state.kind;
    el.hint.textContent =
      state.kind === "listening"
        ? exam.hint_listening
        : state.kind === "reading"
          ? exam.hint_reading
          : "Общий тест: свободная структура без экзаменационного шаблона.";
    el.tabs.innerHTML = state.sections
      .map(
        (section) => `
        <button type="button" class="nav-btn ${section.id === state.active ? "active" : ""}" data-open="${section.id}">
          ${escapeHtml(section.title || "Секция")}
        </button>`
      )
      .join("");
    const section = activeSection();
    if (!section) {
      el.section.innerHTML = "<p class='muted'>Добавьте секцию.</p>";
      el.questions.innerHTML = "";
      return;
    }
    el.section.innerHTML = `
      <div class="row">
        <label class="field" style="flex:1">Название секции
          <input class="input" data-sec="title" value="${escapeAttr(section.title)}">
        </label>
        <label class="field">Тип
          <select class="input" data-sec="kind">
            <option value="passage" ${section.kind === "passage" ? "selected" : ""}>Текст</option>
            <option value="audio" ${section.kind === "audio" ? "selected" : ""}>Аудио</option>
          </select>
        </label>
        <button type="button" class="btn-ghost btn-sm" data-remove-section>Удалить</button>
      </div>
      <label class="field" style="margin-top:12px">${section.kind === "audio" ? "Транскрипт (не виден ученику)" : "Текст пассажа"}
        <textarea class="input reading" rows="10" data-sec="body">${escapeHtml(section.body || "")}</textarea>
      </label>
      ${
        section.kind === "audio"
          ? `<label class="field" style="margin-top:12px">Аудиофайл
              ${
                document.querySelector(`[name="audio_${section.id}"]`)
                  ? `<p class="small muted">Файл выбран и будет сохранён вместе с тестом.</p>`
                  : `<input class="input" type="file" accept="audio/*" data-audio="${section.id}">`
              }
              ${section.audio_url ? `<audio controls src="${section.audio_url}" style="margin-top:8px;width:100%"></audio>` : ""}
            </label>`
          : ""
      }
    `;
    el.types.innerHTML = typeButtons()
      .map(
        (type) =>
          `<button type="button" class="type-chip" data-add-type="${type.id}"><strong>${type.label}</strong>${
            type.hint ? `<span>${type.hint}</span>` : ""
          }</button>`
      )
      .join("");
    const questions = sectionQuestions();
    el.questions.innerHTML = questions.length
      ? questions.map(renderGroup).join("")
      : `<div class="empty">Добавьте группу заданий. Для IELTS Listening Part 1 нажмите <strong>Notes / Form</strong> — ученик увидит бланк с пропусками, как в буклете.</div>`;
  }

  function renderGroup(question) {
    const [from, to] = rangeOf(question);
    const rangeLabel = from === to ? `Q${from}` : `Questions ${from}–${to}`;
    const head = `<div class="qedit-hd">
      <div><strong>${rangeLabel}</strong> · ${labelOf(question.type)}</div>
      <button type="button" class="btn-ghost btn-sm" data-del-q="${question.id}">Удалить</button>
    </div>
    <label class="field">Инструкция ученику
      <textarea class="input" rows="3" data-q="${question.id}" data-field="text">${escapeHtml(question.text)}</textarea>
    </label>
    <label class="field">Вступление к отрывку <span class="muted small">(необязательно)</span>
      <input class="input" data-q="${question.id}" data-field="intro" value="${escapeAttr(question.intro || "")}" placeholder="You will hear a woman booking a weekend course.">
    </label>`;

    if (question.type === "fill_blank" && (question.body || question.title || !(question.items || []).some((item) => item.prompt))) {
      return `<article class="q-card qedit" data-qid="${question.id}">${head}
        <label class="field">Заголовок формы
          <input class="input" data-q="${question.id}" data-field="title" value="${escapeAttr(question.title || "")}" placeholder="Weekend Course Booking Form">
        </label>
        <label class="field">Текст бланка — пропуски как <code>{1}</code>, <code>{2}</code>. Заголовки <code>## Section</code>, пункты <code>*</code>
          <textarea class="input mono notes-body" rows="12" data-q="${question.id}" data-field="body">${escapeHtml(question.body || "")}</textarea>
        </label>
        <label class="field">Правильные ответы по порядку, через запятую. Варианты через /
          <input class="input" data-q="${question.id}" data-field="answers" value="${escapeAttr(question.answers || "")}" placeholder="18 July / 18th July, engineer, magazine">
        </label>
        <div class="notes-block notes-preview">
          ${question.title ? `<div class="nb-title">${escapeHtml(question.title)}</div>` : ""}
          ${notesPreview(question.body)}
        </div>
      </article>`;
    }

    if (question.type === "single" || question.type === "multiple") {
      if (question.type === "single" && question.items?.length) {
        const rows = question.items
          .map((item, index) => {
            const qn = from + index;
            const options = (item.options || question.options || ["", "", ""]).map((option, oi) => {
              const letter = String.fromCharCode(65 + oi);
              return `<div class="option-row">
                <span class="opt-letter">${letter}</span>
                <input class="input" data-q="${question.id}" data-item="${index}" data-item-opt="${oi}" value="${escapeAttr(option)}" placeholder="Option ${letter}">
              </div>`;
            }).join("");
            return `<div class="q-card nested">
              <div class="row"><strong>Q${qn}</strong>
                <button type="button" class="btn-ghost btn-sm" data-rm-item="${question.id}:${index}">✕</button></div>
              <textarea class="input" rows="2" data-q="${question.id}" data-item="${index}" data-item-field="stem" placeholder="Question stem">${escapeHtml(item.stem || "")}</textarea>
              ${options}
              <label class="field">Правильный
                <select class="input" data-q="${question.id}" data-item="${index}" data-item-field="correct">
                  <option value="">—</option>
                  ${(item.options || ["", "", ""]).map((option, oi) => `<option value="${escapeAttr(option)}" ${item.correct === option && option ? "selected" : ""}>${String.fromCharCode(65 + oi)}</option>`).join("")}
                </select>
              </label>
            </div>`;
          })
          .join("");
        return `<article class="q-card qedit" data-qid="${question.id}">${head}${rows}
          <button type="button" class="btn-secondary btn-sm" data-add-item="${question.id}">+ вопрос в группу</button>
        </article>`;
      }
      const options = (question.options || []).map((option, index) => {
        const checked =
          question.type === "multiple"
            ? (question.correct || []).includes(option) && option
            : question.correct === option && option;
        return `<div class="gap">
          <input type="${question.type === "multiple" ? "checkbox" : "radio"}" name="correct-${question.id}" ${checked ? "checked" : ""} data-correct-opt="${question.id}" data-index="${index}">
          <input class="input" data-q="${question.id}" data-opt="${index}" value="${escapeAttr(option)}" placeholder="Вариант ${index + 1}">
        </div>`;
      }).join("");
      return `<article class="q-card qedit" data-qid="${question.id}">${head}
        <p class="small muted">Отметьте правильный ответ.</p>
        ${options}
        <button type="button" class="btn-secondary btn-sm" data-add-opt="${question.id}">Ещё вариант</button>
      </article>`;
    }

    if (question.type === "tfng" || question.type === "ynng") {
      const pairs = question.type === "tfng" ? profile().tfng : profile().ynng;
      const rows = (question.items || [])
        .map((item, index) => {
          const qn = from + index;
          return `<div class="q-card nested">
            <div class="row"><strong>Q${qn}</strong>
              <button type="button" class="btn-ghost btn-sm" data-rm-item="${question.id}:${index}">✕</button></div>
            <textarea class="input" rows="2" data-q="${question.id}" data-item="${index}" data-item-field="stmt" placeholder="Statement">${escapeHtml(item.stmt || item.prompt || "")}</textarea>
            <div class="gap">${pairs
              .map(
                ([value, title]) =>
                  `<label class="choice ${item.correct === value ? "selected" : ""}">
                    <input type="radio" name="tf-${question.id}-${index}" value="${value}" ${item.correct === value ? "checked" : ""} data-q="${question.id}" data-item="${index}" data-item-field="correct"> ${title}
                  </label>`
              )
              .join("")}</div>
          </div>`;
        })
        .join("");
      return `<article class="q-card qedit" data-qid="${question.id}">${head}${rows}
        <button type="button" class="btn-secondary btn-sm" data-add-item="${question.id}">+ утверждение</button>
      </article>`;
    }

    if (question.type === "short") {
      const rows = (question.items || [])
        .map(
          (item, index) => `<div class="gap">
            <span class="muted small">Q${from + index}</span>
            <input class="input" data-q="${question.id}" data-item="${index}" data-item-field="prompt" placeholder="Предложение с _____" value="${escapeAttr(item.prompt || "")}">
            <input class="input" data-q="${question.id}" data-item="${index}" data-item-field="correct" placeholder="ответы через / или запятую" value="${escapeAttr(Array.isArray(item.correct) ? item.correct.join(" / ") : item.correct || "")}">
          </div>`
        )
        .join("");
      return `<article class="q-card qedit" data-qid="${question.id}">${head}${rows}
        <button type="button" class="btn-secondary btn-sm" data-add-item="${question.id}">Ещё пункт</button>
      </article>`;
    }

    if (question.type === "match" || question.type === "heading") {
      const left = (question.left || []).map((value, index) => `<input class="input" data-q="${question.id}" data-left="${index}" value="${escapeAttr(value)}" placeholder="${question.type === "heading" ? "Paragraph A" : "Слева"}">`).join("");
      const right = (question.right || []).map((value, index) => `<input class="input" data-q="${question.id}" data-right="${index}" value="${escapeAttr(value)}" placeholder="${question.type === "heading" ? "Heading i" : "Справа"}">`).join("");
      const keys = (question.left || []).filter(Boolean);
      const map = keys
        .map(
          (key) => `<label class="field">${escapeHtml(key)}
            <select class="input" data-q="${question.id}" data-map="${escapeAttr(key)}">
              <option value="">—</option>
              ${(question.right || [])
                .filter(Boolean)
                .map((value) => `<option value="${escapeAttr(value)}" ${question.correct?.[key] === value ? "selected" : ""}>${escapeHtml(value)}</option>`)
                .join("")}
            </select>
          </label>`
        )
        .join("");
      return `<article class="q-card qedit" data-qid="${question.id}">${head}
        <div class="match-grid">
          <div><p class="small muted">Слева</p>${left}<button type="button" class="btn-ghost btn-sm" data-add-left="${question.id}">+</button></div>
          <div><p class="small muted">Справа / варианты</p>${right}<button type="button" class="btn-ghost btn-sm" data-add-right="${question.id}">+</button></div>
        </div>
        <p class="small muted" style="margin-top:10px">Правильные пары</p>
        ${map}
      </article>`;
    }

    return `<article class="q-card qedit" data-qid="${question.id}">${head}<p class="small muted">Ученик напишет развёрнутый ответ, оценка вручную.</p></article>`;
  }

  function labelOf(type) {
    return typeButtons().find((item) => item.id === type)?.label || type;
  }

  function findQuestion(id) {
    return state.questions.find((item) => item.id === id);
  }

  document.addEventListener("click", (event) => {
    const open = event.target.closest("[data-open]");
    if (open) {
      state.active = open.dataset.open;
      render();
      return;
    }
    if (event.target.closest("#add-section")) {
      const kind = state.kind === "listening" ? "audio" : "passage";
      const exam = profile();
      const section = {
        id: uid("s"),
        db_id: null,
        title:
          kind === "audio"
            ? exam.listening_title.replace("{}", String(state.sections.length + 1))
            : exam.reading_title.replace("{}", String(state.sections.length + 1)),
        kind,
        body: "",
        audio_url: "",
      };
      state.sections.push(section);
      state.active = section.id;
      render();
      return;
    }
    if (event.target.closest("[data-remove-section]") && state.sections.length > 1) {
      const current = state.active;
      state.questions = state.questions.filter((item) => item.sectionId !== current);
      state.sections = state.sections.filter((item) => item.id !== current);
      state.active = state.sections[0].id;
      render();
      return;
    }
    const addType = event.target.closest("[data-add-type]");
    if (addType) {
      state.questions.push(emptyGroup(state.active, addType.dataset.addType));
      render();
      return;
    }
    const del = event.target.closest("[data-del-q]");
    if (del) {
      state.questions = state.questions.filter((item) => item.id !== del.dataset.delQ);
      render();
      return;
    }
    const addOpt = event.target.closest("[data-add-opt]");
    if (addOpt) {
      findQuestion(addOpt.dataset.addOpt)?.options.push("");
      render();
      return;
    }
    const addItem = event.target.closest("[data-add-item]");
    if (addItem) {
      const question = findQuestion(addItem.dataset.addItem);
      if (!question) return;
      if (question.type === "tfng" || question.type === "ynng") question.items.push({ stmt: "", correct: "" });
      else if (question.type === "single") question.items.push({ stem: "", options: ["", "", ""], correct: "" });
      else question.items.push({ prompt: "", correct: "" });
      render();
      return;
    }
    const rmItem = event.target.closest("[data-rm-item]");
    if (rmItem) {
      const [qid, index] = rmItem.dataset.rmItem.split(":");
      const question = findQuestion(qid);
      if (question?.items) question.items.splice(Number(index), 1);
      render();
      return;
    }
    const addLeft = event.target.closest("[data-add-left]");
    if (addLeft) {
      findQuestion(addLeft.dataset.addLeft)?.left.push("");
      render();
      return;
    }
    const addRight = event.target.closest("[data-add-right]");
    if (addRight) {
      findQuestion(addRight.dataset.addRight)?.right.push("");
      render();
    }
  });

  document.addEventListener("input", (event) => {
    const secField = event.target.dataset.sec;
    if (secField) {
      const section = activeSection();
      if (section) section[secField] = event.target.value;
      if (secField === "title") {
        const btn = el.tabs.querySelector(`[data-open="${section.id}"]`);
        if (btn) btn.textContent = section.title || "Секция";
      }
      if (secField === "kind") render();
      return;
    }
    const qid = event.target.dataset.q;
    if (!qid) return;
    const question = findQuestion(qid);
    if (!question) return;
    if (event.target.dataset.field === "text") question.text = event.target.value;
    if (event.target.dataset.field === "intro") question.intro = event.target.value;
    if (event.target.dataset.field === "title") {
      question.title = event.target.value;
      const preview = event.target.closest(".q-card")?.querySelector(".nb-title") || event.target.closest(".q-card")?.querySelector(".notes-preview");
      const block = event.target.closest(".q-card")?.querySelector(".notes-preview");
      if (block) {
        block.innerHTML = `${question.title ? `<div class="nb-title">${escapeHtml(question.title)}</div>` : ""}${notesPreview(question.body)}`;
      }
    }
    if (event.target.dataset.field === "body") {
      question.body = event.target.value;
      const block = event.target.closest(".q-card")?.querySelector(".notes-preview");
      if (block) {
        block.innerHTML = `${question.title ? `<div class="nb-title">${escapeHtml(question.title)}</div>` : ""}${notesPreview(question.body)}`;
      }
    }
    if (event.target.dataset.field === "answers") question.answers = event.target.value;
    if (event.target.dataset.field === "points") question.points = Number(event.target.value || 1);
    if (event.target.dataset.field === "correct" && event.target.dataset.item === undefined) question.correct = event.target.value;
    if (event.target.dataset.opt !== undefined) {
      question.options[Number(event.target.dataset.opt)] = event.target.value;
    }
    if (event.target.dataset.item !== undefined) {
      const index = Number(event.target.dataset.item);
      if (!question.items[index]) question.items[index] = { prompt: "", stmt: "", stem: "", correct: "", options: ["", "", ""] };
      if (event.target.dataset.itemOpt !== undefined) {
        question.items[index].options = question.items[index].options || ["", "", ""];
        question.items[index].options[Number(event.target.dataset.itemOpt)] = event.target.value;
        return;
      }
      const field = event.target.dataset.itemField;
      if (field) question.items[index][field] = event.target.value;
    }
    if (event.target.dataset.left !== undefined) question.left[Number(event.target.dataset.left)] = event.target.value;
    if (event.target.dataset.right !== undefined) question.right[Number(event.target.dataset.right)] = event.target.value;
  });

  document.addEventListener("change", (event) => {
    if (event.target.dataset.correctOpt !== undefined) {
      const question = findQuestion(event.target.dataset.correctOpt);
      if (!question) return;
      const value = question.options[Number(event.target.dataset.index)];
      if (question.type === "multiple") {
        const set = new Set(question.correct || []);
        if (event.target.checked) set.add(value);
        else set.delete(value);
        question.correct = [...set];
      } else {
        question.correct = value;
      }
    }
    if (event.target.dataset.map !== undefined) {
      const question = findQuestion(event.target.dataset.q);
      if (!question) return;
      question.correct = question.correct || {};
      question.correct[event.target.dataset.map] = event.target.value;
    }
    if (event.target.dataset.itemField === "correct") {
      const question = findQuestion(event.target.dataset.q);
      const index = Number(event.target.dataset.item);
      if (question?.items?.[index]) question.items[index].correct = event.target.value;
    }
    if (event.target.dataset.audio) {
      event.target.name = `audio_${event.target.dataset.audio}`;
      el.audio.appendChild(event.target);
      render();
    }
  });

  kindSelect?.addEventListener("change", () => {
    const next = kindSelect.value;
    const empty = state.questions.length === 0 && state.sections.every((item) => !item.body && !item.audio_url);
    state.kind = next;
    if (empty) {
      state.sections = defaultSections(next);
      state.active = state.sections[0].id;
    } else {
      state.sections.forEach((section) => {
        section.kind = next === "listening" ? "audio" : "passage";
      });
    }
    const inst = document.getElementById("id_instructions");
    if (inst && !inst.value) inst.placeholder = profile().instruction;
    render();
  });

  groupSelect?.addEventListener("change", () => {
    const empty = state.questions.length === 0 && state.sections.every((item) => !item.body && !item.audio_url);
    if (empty) {
      state.sections = defaultSections(state.kind);
      state.active = state.sections[0].id;
    }
    const inst = document.getElementById("id_instructions");
    if (inst) inst.placeholder = profile().instruction;
    render();
  });

  el.form.addEventListener("submit", () => {
    const snapshot = {
      kind: kindSelect?.value || state.kind,
      sections: state.sections.map((section) => ({
        id: section.id,
        db_id: section.db_id,
        title: section.title,
        kind: section.kind,
        body: section.body,
      })),
      questions: state.questions.map((question) => ({
        ...question,
        items: (question.items || []).map((item) => ({
          prompt: item.prompt,
          stmt: item.stmt,
          stem: item.stem,
          options: item.options,
          correct: item.correct,
        })),
      })),
    };
    el.json.value = JSON.stringify(snapshot);
  });

  render();
})();
