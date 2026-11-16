(() => {
  const root = document.documentElement;
  const saved = localStorage.getItem("aula-theme");
  if (saved) root.setAttribute("data-theme", saved);
  else root.setAttribute("data-theme", "dark");

  document.addEventListener("click", (event) => {
    const themeBtn = event.target.closest("[data-theme-toggle]");
    if (themeBtn) {
      const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      localStorage.setItem("aula-theme", next);
    }
    const menuBtn = event.target.closest("[data-menu-toggle]");
    if (menuBtn) {
      document.querySelector(".sidebar")?.classList.toggle("open");
    }
    const choice = event.target.closest("[data-choice]");
    if (choice) {
      const name = choice.dataset.name;
      document.querySelectorAll(`[data-choice][data-name="${name}"]`).forEach((node) => node.classList.remove("selected"));
      choice.classList.add("selected");
      const input = document.getElementById(choice.dataset.target);
      if (input) input.value = choice.dataset.value;
    }
    const word = event.target.closest("[data-word]");
    if (word) {
      const target = document.querySelector(word.dataset.wordTarget || "#sentence-box");
      if (!target) return;
      if (word.parentElement === target) {
        document.getElementById("word-bank")?.appendChild(word);
      } else {
        target.appendChild(word);
      }
      const hidden = document.getElementById("sentence-hidden");
      if (hidden) {
        hidden.innerHTML = "";
        [...target.querySelectorAll("[data-word]")].forEach((node) => {
          const input = document.createElement("input");
          input.type = "hidden";
          input.name = "words";
          input.value = node.dataset.word;
          hidden.appendChild(input);
        });
      }
    }
  });

  document.querySelectorAll(".toast").forEach((toast) => {
    setTimeout(() => toast.remove(), 5200);
  });

  document.querySelectorAll("[data-multi-files]").forEach((zone) => {
    const bucket = zone.querySelector("[data-file-bucket]");
    const list = zone.querySelector("[data-picked]");
    const empty = zone.querySelector("[data-file-empty]");
    if (!bucket || !list) return;
    const kept = [];
    const keyOf = (file) => `${file.name}:${file.size}:${file.lastModified}`;
    const sync = () => {
      const transfer = new DataTransfer();
      kept.forEach((file) => transfer.items.add(file));
      bucket.files = transfer.files;
      list.replaceChildren();
      kept.forEach((file, index) => {
        const chip = document.createElement("span");
        chip.className = "file-chip";
        const name = document.createElement("span");
        name.textContent = file.name;
        const remove = document.createElement("button");
        remove.type = "button";
        remove.className = "btn-ghost btn-sm";
        remove.textContent = "×";
        remove.setAttribute("aria-label", zone.dataset.removeLabel || "Убрать");
        remove.addEventListener("click", () => {
          kept.splice(index, 1);
          sync();
        });
        chip.append(name, remove);
        list.append(chip);
      });
      if (empty) empty.hidden = kept.length > 0;
    };
    const addFiles = (files) => {
      [...files].forEach((file) => {
        if (!file || !file.name || !file.size) return;
        const key = keyOf(file);
        if (!kept.some((item) => keyOf(item) === key)) kept.push(file);
      });
      sync();
    };
    zone.querySelectorAll("[data-file-source]").forEach((source) => {
      source.addEventListener("change", () => {
        addFiles(source.files || []);
        source.value = "";
      });
    });
    zone.querySelectorAll("[data-pick]").forEach((button) => {
      button.addEventListener("click", () => {
        zone.querySelector(`[data-file-source="${button.dataset.pick}"]`)?.click();
      });
    });
    ["dragenter", "dragover"].forEach((eventName) => {
      zone.addEventListener(eventName, (event) => {
        event.preventDefault();
        zone.classList.add("over");
      });
    });
    ["dragleave", "drop"].forEach((eventName) => {
      zone.addEventListener(eventName, (event) => {
        event.preventDefault();
        zone.classList.remove("over");
      });
    });
    zone.addEventListener("drop", (event) => addFiles(event.dataTransfer?.files || []));
  });

  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  document.querySelectorAll(".market [data-rise]").forEach((node) => {
    const siblings = [...node.parentElement.querySelectorAll(":scope > [data-rise]")];
    const index = Math.max(0, siblings.indexOf(node));
    if (index) node.style.transitionDelay = `${Math.min(index, 4) * 70}ms`;
  });
  if (reduce) {
    document.querySelectorAll(".market [data-rise]").forEach((node) => node.classList.add("is-in"));
  } else {
    const rises = [...document.querySelectorAll(".market [data-rise]")];
    const heroLines = rises.filter((node) => node.closest(".hero-copy"));
    const later = rises.filter((node) => !node.closest(".hero-copy"));
    const watch = (nodes, options) => {
      if (!nodes.length) return;
      if (!("IntersectionObserver" in window)) {
        nodes.forEach((node) => node.classList.add("is-in"));
        return;
      }
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add("is-in");
          observer.unobserve(entry.target);
        });
      }, options);
      nodes.forEach((node) => observer.observe(node));
    };
    watch(later, { threshold: 0.15 });
    watch(heroLines, { threshold: 0.35, rootMargin: "0px 0px -18% 0px" });
    window.addEventListener("pointermove", (event) => {
      root.style.setProperty("--mx", `${event.clientX}px`);
      root.style.setProperty("--my", `${event.clientY}px`);
    }, { passive: true });
    if (document.querySelector(".market") && window.matchMedia("(pointer: fine)").matches) {
      let rendered = window.scrollY;
      let goal = rendered;
      let frame = 0;
      const clamp = (y) => {
        const max = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
        return Math.min(max, Math.max(0, y));
      };
      const step = () => {
        frame = 0;
        const next = rendered + (goal - rendered) * 0.1;
        rendered = Math.abs(goal - next) < 0.6 ? goal : next;
        window.scrollTo({ top: rendered, left: 0, behavior: "instant" });
        if (rendered !== goal) frame = requestAnimationFrame(step);
      };
      window.addEventListener("wheel", (event) => {
        if (event.ctrlKey || event.metaKey) return;
        event.preventDefault();
        let dy = event.deltaY;
        if (event.deltaMode === 1) dy *= 16;
        else if (event.deltaMode === 2) dy *= window.innerHeight;
        const distance = Math.abs(dy);
        const softened = Math.sign(dy) * (Math.min(distance, 64) + Math.max(0, distance - 64) * 0.4);
        goal = clamp(goal + softened);
        if (!frame) frame = requestAnimationFrame(step);
      }, { passive: false });
      window.addEventListener("scroll", () => {
        if (Math.abs(window.scrollY - rendered) <= 2) return;
        rendered = goal = window.scrollY;
        if (frame) {
          cancelAnimationFrame(frame);
          frame = 0;
        }
      }, { passive: true });
    }
  }

  const frames = document.querySelectorAll(".market .shot-frame");
  const tiltEls = document.querySelectorAll(".market .scenario-card, .market .scenario-tile, .market .example-card, .market .certs-frame");
  if (!reduce && (frames.length || tiltEls.length)) {
    let ticking = false;
    const placeShots = () => {
      ticking = false;
      const view = window.innerHeight || 1;
      frames.forEach((frame) => {
        const img = frame.querySelector("img");
        if (!img) return;
        const rect = frame.getBoundingClientRect();
        const progress = (view - rect.top) / (view + rect.height);
        const clamped = Math.min(1, Math.max(0, progress));
        const extra = img.offsetHeight - frame.clientHeight;
        img.style.transform = extra > 0 ? `translate3d(0, ${(-extra * clamped).toFixed(1)}px, 0)` : "none";
      });
      tiltEls.forEach((el) => {
        const rect = el.getBoundingClientRect();
        const p = Math.min(1, Math.max(0, (view * 0.92 - rect.top) / (view * 0.62)));
        if (p >= 0.98) {
          el.classList.add("is-settled");
        } else {
          el.classList.remove("is-settled");
          el.style.setProperty("--tp", p.toFixed(3));
        }
      });
    };
    const onScroll = () => {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(placeShots);
    };
    frames.forEach((frame) => {
      const img = frame.querySelector("img");
      if (img && !img.complete) img.addEventListener("load", onScroll, { once: true });
    });
    placeShots();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
  }
})();
