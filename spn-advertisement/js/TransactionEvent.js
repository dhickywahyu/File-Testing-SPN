let CURRENT_TRX = {};
var GLOBAL_INTERVAL;

function generateBillEmoneyProcess({
  transaction: transaction,
  spotName = "",
  spotAdress = "",
}) {
  REFRESH_TRANSACTION(transaction);
  document.getElementById("parkingImage__EMONEY_PROCESS").src =
    transaction.image;
  document.getElementById("parkingSpotName__EMONEY_PROCESS").innerHTML =
    spotName;
  document.getElementById("parkingSpotAddress__EMONEY_PROCESS").innerHTML =
    spotAdress;
  document.getElementById("searchKey__EMONEY_PROCESS").innerHTML =
    CURRENT_TRX.search_key;
  document.getElementById("timeIn__EMONEY_PROCESS").innerHTML =
    CURRENT_TRX.time_in;
  document.getElementById("duration__EMONEY_PROCESS").innerHTML =
    CURRENT_TRX.total_hours;
  document.getElementById("timeOut__EMONEY_PROCESS").innerHTML = "-";
  document.getElementById("licensePlate__EMONEY_PROCESS").innerHTML =
    CURRENT_TRX.license_plate ?? "Tidak Terdeteksi";
  document.getElementById("amount__EMONEY_PROCESS").innerHTML =
    CURRENT_TRX.amount;

  var timer = 30;
  if (timer > 0) {
    document.getElementById("timer__EMONEY_PROCESS").classList.remove("hidden");
    GLOBAL_INTERVAL = setInterval(() => {
      timer = parseInt(timer) - 1;
      if (timer === 0) {
        forceClearInterval();
        window.location.href = "http://spn.gate.soulparking.co.id/";
      }
      document.getElementById("timer__EMONEY_PROCESS").innerText = timer;
    }, 1100);
  } else {
    document.getElementById("timer__EMONEY_PROCESS").classList.add("hidden");
  }
}

function generateBillEmoneySuccess({ cardInfo, spotName, spotAdress }) {
  document.getElementById("balanceLeft__EMONEY_SUCCESS").innerHTML =
    cardInfo.left_amount;
  document.getElementById("cardBank__EMONEY_SUCCESS").innerHTML =
    cardInfo.card_type;
  document.getElementById("cardNumber__EMONEY_SUCCESS").innerHTML =
    generateCardNumber(cardInfo.card_number);
  document.getElementById("parkingImage__EMONEY_SUCCESS").src =
    CURRENT_TRX.image;
  document.getElementById("parkingSpotName__EMONEY_SUCCESS").innerHTML =
    spotName;
  document.getElementById("parkingSpotAddress__EMONEY_SUCCESS").innerHTML =
    spotAdress;
  document.getElementById("searchKey__EMONEY_SUCCESS").innerHTML =
    CURRENT_TRX.search_key;
  document.getElementById("timeIn__EMONEY_SUCCESS").innerHTML =
    CURRENT_TRX.time_in;
  document.getElementById("duration__EMONEY_SUCCESS").innerHTML =
    CURRENT_TRX.total_hours;
  document.getElementById("timeOut__EMONEY_SUCCESS").innerHTML = "-";
  document.getElementById("licensePlate__EMONEY_SUCCESS").innerHTML =
    CURRENT_TRX.license_plate ?? "Tidak Terdeteksi";
  document.getElementById("amount__EMONEY_SUCCESS").innerHTML =
    CURRENT_TRX.amount;
}

function generateBillQRISProcess({ spotName, spotAdress }) {
  forceClearInterval();
  document.getElementById("loader__QRIS").classList.add("hidden");
  document.getElementById("image__QRIS").classList.add("hidden");
  document.getElementById("loader__QRIS").classList.remove("hidden");
  document.getElementById("parkingImage__QRIS").src = CURRENT_TRX.image;
  document.getElementById("parkingSpotName__QRIS").innerHTML = spotName;
  document.getElementById("parkingSpotAddress__QRIS").innerHTML = spotAdress;
  document.getElementById("searchKey__QRIS").innerHTML = CURRENT_TRX.search_key;
  document.getElementById("timeIn__QRIS").innerHTML = CURRENT_TRX.time_in;
  document.getElementById("duration__QRIS").innerHTML = CURRENT_TRX.total_hours;
  document.getElementById("timeOut__QRIS").innerHTML = "-";
  document.getElementById("licensePlate__QRIS").innerHTML =
    CURRENT_TRX.license_plate ?? "Tidak Terdeteksi";
  document.getElementById("amount__QRIS").innerHTML = CURRENT_TRX.amount;
}

function generateBillQRISCreated({ qrisData, spotName, spotAdress }) {
  forceClearInterval();
  document.getElementById("loader__QRIS").classList.add("hidden");
  document.getElementById("image__QRIS").classList.add("hidden");
  document.getElementById("image__QRIS").classList.remove("hidden");
  document.getElementById("parkingImage__QRIS").src = CURRENT_TRX.image;
  document.getElementById("parkingSpotName__QRIS").innerHTML = spotName;
  document.getElementById("parkingSpotAddress__QRIS").innerHTML = spotAdress;
  document.getElementById("searchKey__QRIS").innerHTML = CURRENT_TRX.search_key;
  document.getElementById("timeIn__QRIS").innerHTML = CURRENT_TRX.time_in;
  document.getElementById("duration__QRIS").innerHTML = CURRENT_TRX.total_hours;
  document.getElementById("timeOut__QRIS").innerHTML = "-";
  document.getElementById("licensePlate__QRIS").innerHTML =
    CURRENT_TRX.license_plate ?? "Tidak Terdeteksi";
  document.getElementById("amount__QRIS").innerHTML = CURRENT_TRX.amount;
  document.getElementById("qr__QRIS").src = qrisData.image;
}

function generateSuccessPaymentQRIS({ spotName, spotAdress }) {
  document.getElementById("parkingImage__QRIS_SUCCESS").src = CURRENT_TRX.image;
  document.getElementById("parkingSpotName__QRIS_SUCCESS").innerHTML = spotName;
  document.getElementById("parkingSpotAddress__QRIS_SUCCESS").innerHTML =
    spotAdress;
  document.getElementById("searchKey__QRIS_SUCCESS").innerHTML =
    CURRENT_TRX.search_key;
  document.getElementById("timeIn__QRIS_SUCCESS").innerHTML =
    CURRENT_TRX.time_in;
  document.getElementById("duration__QRIS_SUCCESS").innerHTML =
    CURRENT_TRX.total_hours;
  document.getElementById("timeOut__QRIS_SUCCESS").innerHTML = "-";
  document.getElementById("licensePlate__QRIS_SUCCESS").innerHTML =
    CURRENT_TRX.license_plate ?? "Tidak Terdeteksi";
  document.getElementById("amount__QRIS_SUCCESS").innerHTML =
    CURRENT_TRX.amount;
  document.getElementById("smallAdvertisingGateOutQRIS").src =
    "src/img/sample-ads-1.png";
}

function forceClearInterval() {
  clearInterval(GLOBAL_INTERVAL);
}

function generateMembershipCard({
  isShowMember,
  isShowRFID = false,
  spotName,
  dayLeftIn = null,
  rfidIn = 0,
  subCaption = "Mohon untuk tidak meninggalkan barang berharga di dalam kendaraan anda.",
}) {
  let greeting = "Selamat datang di";
  let caption = spotName;
  if (isShowRFID) {
    subCaption += `RFID: ${rfidIn}`;
  }
  if (isShowMember) {
    greeting = "Selamat Datang";
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

function generateGateOutMember() {
  document.getElementById("smallAdvertisingGateOutMember").src =
    "src/img/sample-ads-1.png";
}

function REFRESH_TRANSACTION(TRX) {
  CURRENT_TRX = TRX;
}

function CLEAR_TRANSACTION() {
  CURRENT_TRX = null;
}

function generateCardNumber(CARD_NUMBER) {
  CARD_NUMBER = CARD_NUMBER.toString();
  return `XXXX-XXXX-XXXX-${CARD_NUMBER.substr(
    CARD_NUMBER.length - 4,
    CARD_NUMBER.length
  )}`;
}
