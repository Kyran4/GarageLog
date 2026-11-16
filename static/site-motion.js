import { animate, inView, stagger } from "https://cdn.jsdelivr.net/npm/motion@14.14.0/+esm";

if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    const hero = document.querySelector(".gl-hero");

    if (hero) {
        const heroItems = hero.querySelectorAll(
            ".gl-badge, .gl-logo-mark, h1, .lead, .gl-hero-actions, .gl-stat"
        );

        animate(
            heroItems,
            { opacity: [0, 1], y: [22, 0], scale: [0.98, 1] },
            { duration: 0.65, delay: stagger(0.1), ease: "easeOut" }
        );
    }

    inView(
        ".gl-motion, .gl-banner, .gl-panel, .gl-auth, main .gl-card",
        element => {
            animate(
                element,
                { opacity: [0, 1], y: [18, 0] },
                { duration: 0.5, ease: "easeOut" }
            );
        },
        { amount: 0.15 }
    );
}
