function generateCaptionGate({
  isShowMember,
  isShowRFID = false,
  isExitMember = false,
  caption,
  dayLeftIn = null,
  rfidIn = 0,
  greeting = "Selamat datang di",
  subCaption = "Mohon untuk tidak meninggalkan barang berharga di dalam kendaraan anda.",
}) {
  if (isShowRFID) {
    subCaption += `RFID: ${rfidIn}`;
  }
  if (isShowMember) {
    greeting = "Selamat Datang";
    caption = `Membership Anda &nbsp; &nbsp; &nbsp; Tersisa ${dayLeftIn} Hari.`;
  }

  if (isExitMember) {
    greeting = "Selamat Jalan";
    caption = `Membership Anda &nbsp; &nbsp; &nbsp; Tersisa ${dayLeftIn} Hari.`;
  }

  let wrapper = document.getElementById("captionGateInOpen");
  component = `<p class="text-4xl font-black text-gray-600">${greeting}</p>
            <p class="text-6xl mt-2 font-black text-gray-900">
              ${caption}
            </p>
            <p class="text-gray-500 text-2xl font-bold mt-5">
              ${subCaption}
            </p>`;

  wrapper.innerHTML = component;
}

function generateAdvertisingGateIn() {
  document.getElementById("smallAdvertisingGateIn").src =
    "src/img/sample-ads-1.png";

  document.getElementById("largeAdvertisingGateIn").src =
    "https://blogger.googleusercontent.com/img/b/R29vZ2xl/AVvXsEg4Ta_WYT_mD2Oc3YMRzYkvSCan9WkTBgMs9cxhFOiF3AL52h2jqQb5trTgLrfrw0Y_V1wZVMeiYk2UaNhyphenhyphen1wUvnwcSO87hTlL_nPiP88GT6Tjes0CaK97IqT81Je_HVlxvXT4IuKkpsyb2/s1600/Promo-ADIDAS-9.9-SALE-Promo-Buy-3-Get-30%2525%252C-Buy-3-Get-40%2525-Untuk-Semua-Produk-Sepatu-dan-Pakaian.jpg";
}
