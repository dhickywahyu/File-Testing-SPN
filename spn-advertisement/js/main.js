const OVERLAY = document.getElementById("overlayDynamicIsland");

function processRenderingOverlay(hasOverlay) {
  if (hasOverlay) {
    OVERLAY.classList.remove("hidden");
  } else {
    OVERLAY.classList.add("hidden");
  }
}

function resetIsland(target) {
  processRenderingOverlay();
  document.getElementById("smallDynamicIsland").classList.add("hidden", "flex");
  document.getElementById("largeDynamicIsland").classList.add("hidden", "flex");
  document
    .getElementById("extraLargeDynamicIsland")
    .classList.add("hidden", "flex");
  document.getElementById(target).classList.remove("hidden");
}

function expandIsland(sourceIsland, targetIsland, hasOverlay = false) {
  processRenderingOverlay(hasOverlay);

  const small = document.getElementById(sourceIsland);
  const large = document.getElementById(targetIsland);

  small.classList.remove("flex");
  small.classList.add("hidden");

  large.classList.remove("hidden", "animate-expand", "animate-shrink");
  void large.offsetWidth;
  large.classList.add("flex", "animate-expand");
}

function shrinkIsland(sourceIsland, targetIsland, hasOverlay = false) {
  processRenderingOverlay(hasOverlay);

  const large = document.getElementById(sourceIsland);
  const small = document.getElementById(targetIsland);

  large.classList.remove("animate-expand", "animate-shrink");
  void large.offsetWidth;
  large.classList.add("animate-shrink");

  setTimeout(() => {
    large.classList.remove("flex");
    large.classList.add("hidden");

    small.classList.remove("animate-expand", "animate-shrink", "hidden");
    void small.offsetWidth;
    small.classList.add("flex");
  }, 300);
}

function enterAnimation(targetComponent) {
  const target = document.getElementById(targetComponent);
  target.classList.remove("hidden");
  target.classList.remove("animate-slide-down");
  target.classList.add("animate-slide-up");
}

function exitAnimation(targetComponent) {
  const target = document.getElementById(targetComponent);
  target.classList.add("hidden");
  target.classList.remove("animate-slide-up");
  target.classList.add("animate-slide-down");
  setTimeout(() => {
    target.classList.add("hidden");
  }, 1000);
}

function processRenderPrice(price) {
  document.getElementById("motorcycle__IDLE").classList.add("hidden");
  document.getElementById("car__IDLE").classList.add("hidden");
  document.getElementById("limitedProgressive__IDLE").classList.add("hidden");

  if (price.vehicle_code === "MT1") {
    document.getElementById("motorcycle__IDLE").classList.remove("hidden");
    document.getElementById("vehicleType__IDLE").innerHTML = "Motor";
  } else {
    document.getElementById("car__IDLE").classList.remove("hidden");
    document.getElementById("vehicleType__IDLE").innerHTML = "Mobil";
  }

  document.getElementById("startPrice__IDLE").innerHTML =
    `Rp${formatIndonesianCurrency(price.price)}`;
  document.getElementById("startHour__IDLE").innerHTML = price.initial_time;

  document.getElementById("nextPrice__IDLE").innerHTML =
    `Rp${formatIndonesianCurrency(price.next_price)}`;
  document.getElementById("nextHour__IDLE").innerHTML = "1";

  if (price.type === "LIMITED_PROGRESSIVE") {
    document.getElementById("maxPrice__IDLE").innerHTML =
      `Rp${formatIndonesianCurrency(price.max_price)}`;
    document.getElementById("maxHour__IDLE").innerHTML = price.max_hour;
    document
      .getElementById("limitedProgressive__IDLE")
      .classList.remove("hidden");
  }
}

function formatIndonesianCurrency(angka) {
  return angka.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}
