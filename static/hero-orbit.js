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
    var pointerTargetActive = 0;
    var pointerInfluence = 0;
    var pulseStart = 0;
    var pulseX = 0;
    var pulseY = 0;

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
        pulseX = bounds.width / 2;
        pulseY = bounds.height / 2;
        createPoints();
        draw(0);
    }

    function updatePointer(clientX, clientY) {
        var bounds = canvas.getBoundingClientRect();
        var centerX = bounds.left + bounds.width / 2;
        var centerY = bounds.top + bounds.height / 2;
        var sphereRadius = Math.min(bounds.width, bounds.height) * 0.43 * 0.84;
        var offsetX = (clientX - centerX) / sphereRadius;
        var offsetY = (clientY - centerY) / (sphereRadius * 0.96);
        var insideSphere = offsetX * offsetX + offsetY * offsetY <= 1;

        targetPointerX = insideSphere ? offsetX : 0;
        targetPointerY = insideSphere ? offsetY : 0;
        pointerTargetActive = insideSphere ? 1 : 0;
        hero.style.cursor = insideSphere ? "pointer" : "";

        if (reducedMotion.matches) {
            pointerX = targetPointerX;
            pointerY = targetPointerY;
            pointerInfluence = pointerTargetActive;
            hero.style.setProperty("--gl-hero-pointer-x", ((pointerX + 1) * 50) + "%");
            hero.style.setProperty("--gl-hero-pointer-y", ((pointerY + 1) * 50) + "%");
            draw(0);
        }

        return insideSphere;
    }

    function draw(time) {
        var width = canvas.clientWidth;
        var height = canvas.clientHeight;
        pointerX += (targetPointerX - pointerX) * 0.055;
        pointerY += (targetPointerY - pointerY) * 0.055;
        pointerInfluence += (pointerTargetActive - pointerInfluence) * 0.08;
        var centerX = width / 2 + pointerX * width * 0.018;
        var centerY = height / 2 + pointerY * height * 0.018;
        var radius = Math.min(width, height) * 0.43;
        var pointerFieldX = centerX + pointerX * radius * 0.84;
        var pointerFieldY = centerY + pointerY * radius * 0.84;
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
        var pulseProgress = pulseStart ? (time - pulseStart) / 760 : 1;

        if (pulseProgress >= 1) {
            pulseStart = 0;
            pulseProgress = 1;
        }

        points.forEach(function (point) {
            var rotatedX = point.x * cosRotation - point.z * sinRotation;
            var rotatedZ = point.x * sinRotation + point.z * cosRotation;
            var rotatedY = point.y * cosTilt - rotatedZ * sinTilt;
            var depth = point.y * sinTilt + rotatedZ * cosTilt;
            var perspective = 1 / (1.45 - depth * 0.24);
            var shimmer = reducedMotion.matches ? 0.82 : 0.68 + Math.sin(time * 0.002 + point.phase) * 0.24;
            var x = centerX + rotatedX * radius * perspective;
            var y = centerY + rotatedY * radius * perspective;
            var ripple = 0;
            var pointerDistance = Math.hypot(x - pointerFieldX, y - pointerFieldY);
            var pointerStrength = Math.max(0, 1 - pointerDistance / (radius * 0.34)) * pointerInfluence;
            if (pointerStrength > 0) {
                var pointerDisplacement = radius * 0.055 * pointerStrength / Math.max(pointerDistance, 1);
                x += (x - pointerFieldX) * pointerDisplacement;
                y += (y - pointerFieldY) * pointerDisplacement;
            }

            if (pulseStart && pulseProgress >= 0) {
                var distance = Math.hypot(x - pulseX, y - pulseY);
                var bandWidth = radius * 0.055;
                var firstFront = radius * (0.035 + pulseProgress * 0.68);
                ripple = Math.max(0, 1 - Math.abs(distance - firstFront) / bandWidth) * (1 - pulseProgress);

                var trailingProgress = (pulseProgress - 0.2) / 0.8;
                if (trailingProgress >= 0 && trailingProgress < 1) {
                    var trailingFront = radius * (0.035 + trailingProgress * 0.68);
                    var trailingWave = Math.max(0, 1 - Math.abs(distance - trailingFront) / bandWidth);
                    ripple = Math.max(ripple, trailingWave * (1 - trailingProgress) * 0.58);
                }

                if (distance > 0 && ripple > 0) {
                    var displacement = radius * 0.018 * ripple / distance;
                    x += (x - pulseX) * displacement;
                    y += (y - pulseY) * displacement;
                }
            }

            projected.push({
                x: x,
                y: y,
                depth: depth,
                alpha: (0.18 + (depth + 1) * 0.34) * shimmer,
                size: point.size * (0.72 + (depth + 1) * 0.3) + pointerStrength * 0.45,
                warm: rotatedX * 0.5 + 0.5,
                ripple: Math.max(ripple, pointerStrength * 0.38)
            });
        });

        projected.sort(function (a, b) { return a.depth - b.depth; });
        projected.forEach(function (point) {
            var red = Math.round(78 + point.warm * 177);
            var green = Math.round(191 + point.warm * 8);
            var blue = Math.round(255 - point.warm * 121);
            var rippleTint = point.ripple * 0.72;
            red = Math.round(red + (139 - red) * rippleTint);
            green = Math.round(green + (222 - green) * rippleTint);
            blue = Math.round(blue + (255 - blue) * rippleTint);
            context.fillStyle = "rgba(" + red + ", " + green + ", " + blue + ", " + Math.min(1, point.alpha + point.ripple * 0.28) + ")";
            context.beginPath();
            context.arc(point.x, point.y, point.size + point.ripple * 0.8, 0, Math.PI * 2);
            context.fill();
        });

        if (!reducedMotion.matches && visible && !document.hidden) {
            frame = window.requestAnimationFrame(draw);
        }
    }

    hero.addEventListener("pointermove", function (event) {
        if (event.pointerType === "touch") return;
        updatePointer(event.clientX, event.clientY);
    });

    hero.addEventListener("pointerleave", function () {
        targetPointerX = 0;
        targetPointerY = 0;
        pointerTargetActive = 0;
        hero.style.cursor = "";
        if (reducedMotion.matches) updatePointer(-1, -1);
    });

    hero.addEventListener("click", function (event) {
        if (event.target.closest("a, button, input, select, textarea, [role='button']")) return;
        if (reducedMotion.matches || !updatePointer(event.clientX, event.clientY)) return;
        var bounds = canvas.getBoundingClientRect();
        pulseX = event.clientX - bounds.left;
        pulseY = event.clientY - bounds.top;
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
