(function () {
    var canvas = document.querySelector(".gl-hero-canvas");
    var hero = document.querySelector(".gl-hero");
    if (!canvas || !hero) return;

    var context = canvas.getContext("2d");
    if (!context) return;

    var reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    var points = [];
    var frame = 0;
    var visible = true;
    var count = 1100;
    var pointerX = 0;
    var pointerY = 0;
    var targetPointerX = 0;
    var targetPointerY = 0;
    var pulseStart = 0;

    function randomGenerator(seed) {
        return function () {
            seed = (seed * 1664525 + 1013904223) % 4294967296;
            return seed / 4294967296;
        };
    }

    function createPoints() {
        var random = randomGenerator(481516);
        var goldenAngle = Math.PI * (3 - Math.sqrt(5));
        points = [];
        count = canvas.clientWidth < 420 ? 620 : 1100;

        for (var index = 0; index < count; index += 1) {
            var y = 1 - (index / (count - 1)) * 2;
            var ringRadius = Math.sqrt(1 - y * y);
            var angle = goldenAngle * index;
            points.push({
                x: Math.cos(angle) * ringRadius,
                y: y,
                z: Math.sin(angle) * ringRadius,
                phase: random() * Math.PI * 2,
                size: 0.45 + random() * 0.95
            });
        }
    }

    function resize() {
        window.cancelAnimationFrame(frame);
        var bounds = canvas.getBoundingClientRect();
        var pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
        canvas.width = Math.round(bounds.width * pixelRatio);
        canvas.height = Math.round(bounds.height * pixelRatio);
        context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
        createPoints();
        draw(0);
    }

    function draw(time) {
        var width = canvas.clientWidth;
        var height = canvas.clientHeight;
        pointerX += (targetPointerX - pointerX) * 0.055;
        pointerY += (targetPointerY - pointerY) * 0.055;
        var centerX = width / 2 + pointerX * width * 0.018;
        var centerY = height / 2 + pointerY * height * 0.018;
        var radius = Math.min(width, height) * 0.43;
        var rotation = (reducedMotion.matches ? 0 : time * 0.00012) + pointerX * 0.34;
        var tilt = 0.24 + pointerY * 0.18;

        context.clearRect(0, 0, width, height);
        hero.style.setProperty("--gl-hero-pointer-x", ((pointerX + 1) * 50) + "%");
        hero.style.setProperty("--gl-hero-pointer-y", ((pointerY + 1) * 50) + "%");

        var glow = context.createRadialGradient(centerX, centerY, radius * 0.1, centerX, centerY, radius * 1.12);
        glow.addColorStop(0, "rgba(17, 81, 115, 0.12)");
        glow.addColorStop(0.65, "rgba(10, 52, 83, 0.06)");
        glow.addColorStop(1, "rgba(10, 52, 83, 0)");
        context.fillStyle = glow;
        context.fillRect(0, 0, width, height);

        var orbit = context.createLinearGradient(centerX - radius, centerY, centerX + radius, centerY);
        orbit.addColorStop(0, "rgba(92, 205, 255, 0)");
        orbit.addColorStop(0.28, "rgba(92, 205, 255, 0.24)");
        orbit.addColorStop(0.72, "rgba(255, 195, 103, 0.32)");
        orbit.addColorStop(1, "rgba(255, 195, 103, 0)");
        context.save();
        context.translate(centerX, centerY);
        context.rotate(-0.2 + Math.sin(rotation * 0.7) * 0.08);
        context.beginPath();
        context.ellipse(0, 0, radius * 1.03, radius * 0.34, 0, 0, Math.PI * 2);
        context.strokeStyle = orbit;
        context.lineWidth = 1;
        context.stroke();
        context.restore();

        var projected = [];
        var cosRotation = Math.cos(rotation);
        var sinRotation = Math.sin(rotation);
        var cosTilt = Math.cos(tilt);
        var sinTilt = Math.sin(tilt);

        points.forEach(function (point) {
            var rotatedX = point.x * cosRotation - point.z * sinRotation;
            var rotatedZ = point.x * sinRotation + point.z * cosRotation;
            var rotatedY = point.y * cosTilt - rotatedZ * sinTilt;
            var depth = point.y * sinTilt + rotatedZ * cosTilt;
            var perspective = 1 / (1.45 - depth * 0.24);
            var shimmer = reducedMotion.matches ? 0.82 : 0.68 + Math.sin(time * 0.002 + point.phase) * 0.24;

            projected.push({
                x: centerX + rotatedX * radius * perspective,
                y: centerY + rotatedY * radius * perspective,
                depth: depth,
                alpha: (0.18 + (depth + 1) * 0.34) * shimmer,
                size: point.size * (0.72 + (depth + 1) * 0.3),
                warm: rotatedX * 0.5 + 0.5
            });
        });

        projected.sort(function (a, b) { return a.depth - b.depth; });
        projected.forEach(function (point) {
            var red = Math.round(78 + point.warm * 177);
            var green = Math.round(191 + point.warm * 8);
            var blue = Math.round(255 - point.warm * 121);
            context.fillStyle = "rgba(" + red + ", " + green + ", " + blue + ", " + point.alpha + ")";
            context.beginPath();
            context.arc(point.x, point.y, point.size, 0, Math.PI * 2);
            context.fill();
        });

        if (pulseStart && !reducedMotion.matches) {
            var pulseProgress = (time - pulseStart) / 680;
            if (pulseProgress >= 1) {
                pulseStart = 0;
            } else if (pulseProgress >= 0) {
                var pulseRadius = radius * (0.4 + pulseProgress * 0.65);
                context.beginPath();
                context.ellipse(centerX, centerY, pulseRadius, pulseRadius * 0.82, 0, 0, Math.PI * 2);
                context.strokeStyle = "rgba(132, 220, 255, " + (0.28 * (1 - pulseProgress)) + ")";
                context.lineWidth = 1;
                context.stroke();
            }
        }

        if (!reducedMotion.matches && visible && !document.hidden) {
            frame = window.requestAnimationFrame(draw);
        }
    }

    hero.addEventListener("pointermove", function (event) {
        if (event.pointerType === "touch") return;
        var bounds = hero.getBoundingClientRect();
        targetPointerX = Math.max(-1, Math.min(1, ((event.clientX - bounds.left) / bounds.width - 0.5) * 2));
        targetPointerY = Math.max(-1, Math.min(1, ((event.clientY - bounds.top) / bounds.height - 0.5) * 2));
        if (reducedMotion.matches) {
            pointerX = targetPointerX;
            pointerY = targetPointerY;
            hero.style.setProperty("--gl-hero-pointer-x", ((pointerX + 1) * 50) + "%");
            hero.style.setProperty("--gl-hero-pointer-y", ((pointerY + 1) * 50) + "%");
        }
    });

    hero.addEventListener("pointerleave", function () {
        targetPointerX = 0;
        targetPointerY = 0;
        if (reducedMotion.matches) {
            pointerX = 0;
            pointerY = 0;
            hero.style.setProperty("--gl-hero-pointer-x", "50%");
            hero.style.setProperty("--gl-hero-pointer-y", "50%");
        }
    });

    hero.addEventListener("click", function (event) {
        if (event.target.closest("a, button, input, select, textarea, [role='button']")) return;
        if (reducedMotion.matches) return;
        pulseStart = window.performance.now();
        updateAnimation();
    });

    function updateAnimation() {
        window.cancelAnimationFrame(frame);
        if (reducedMotion.matches || !visible || document.hidden) {
            draw(0);
            return;
        }
        frame = window.requestAnimationFrame(draw);
    }

    if ("ResizeObserver" in window) {
        new ResizeObserver(resize).observe(canvas);
    } else {
        window.addEventListener("resize", resize);
    }
    if ("IntersectionObserver" in window) {
        new IntersectionObserver(function (entries) {
            visible = entries[0].isIntersecting;
            updateAnimation();
        }).observe(hero);
    }
    document.addEventListener("visibilitychange", updateAnimation);
    if (reducedMotion.addEventListener) {
        reducedMotion.addEventListener("change", updateAnimation);
    } else if (reducedMotion.addListener) {
        reducedMotion.addListener(updateAnimation);
    }

    resize();
    updateAnimation();
})();
