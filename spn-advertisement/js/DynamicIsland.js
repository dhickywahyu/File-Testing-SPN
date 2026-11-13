function setSmallDynamicIsland({ color = "red", text = "" }) {
  let component = `<div class="flex space-x-3 align-middle">
            <div class="mt-1">
              <span class="relative flex h-6 w-6">
                <span
                  class="animate-ping absolute inline-flex h-full w-full rounded-full bg-${color}-400 opacity-75"
                ></span>
                <span
                  class="relative inline-flex rounded-full h-6 w-6 bg-${color}-500"
                ></span>
              </span>
            </div>
            <div class="">${text}</div>
          </div>`;

  document.getElementById("smallDynamicIsland__content").innerHTML = component;
}

function setExtraLargeDynamicIsland({
  title = "",
  content = "",
  type = "MEMBER_ERROR",
  hasBadge = false,
  badge = "",
  badgeBackgroundColor = "gray",
  badgeTextColor = "black",
}) {
  let badgeComponent = ``;
  document.getElementById("extraLargeDynamicIsland__title").innerHTML = title;
  document.getElementById("extraLargeDynamicIsland__content").innerHTML =
    content;
  document.getElementById("extraLargeDynamicIsland__badge").innerHTML = "";

  document
    .getElementById("extraLargeDynamicIsland__MEMBER_ERROR__icon")
    .classList.add("hidden");
  document
    .getElementById("extraLargeDynamicIsland__GENERAL_ERROR__icon")
    .classList.add("hidden");

  document
    .getElementById(`extraLargeDynamicIsland__${type}__icon`)
    .classList.remove("hidden");
  if (hasBadge) {
    badgeComponent = `<span
                  class="bg-${badgeBackgroundColor}-300 rounded-xl font-black text-lg px-5 py-3 text-${badgeTextColor}"
                >
                  ${badge}
                </span>`;
    document.getElementById("extraLargeDynamicIsland__badge").innerHTML =
      badgeComponent;
  }
}

function setLargeDynamicIsland({ text = [] }) {
  let component = "";
  for (let item = 0; item < text.length; item++) {
    component += `<p>${text[item]}</p>`;
  }

  document.getElementById("largeDynamicIsland__content").innerHTML = component;
}
