// Saisie du téléphone (web) : `npm run test:bo`. Même normalisation que Django (libphonenumber), sans jamais exiger l'indicatif.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  allCountries, countryName, displayPhone, exampleNational, flagOf, formatNational, fromE164, maskPhone, phoneError, searchCountries,
  splitInternational, toE164,
} from "./phone.ts";

test("numéro national + pays → E.164, sans saisir l'indicatif", () => {
  assert.equal(toE164({ country: "CI", national: "07 00 00 00 00" }), "+2250700000000");
  assert.equal(toE164({ country: "CI", national: "0594977511" }), "+2250594977511");
  assert.equal(toE164({ country: "FR", national: "06 12 34 56 78" }), "+33612345678");
  assert.equal(toE164({ country: "SN", national: "77 123 45 67" }), "+221771234567");
  assert.equal(toE164({ country: "CI", national: "07 00" }), null);
});

test("messages d'erreur clairs avec le pays et un exemple", () => {
  assert.equal(phoneError({ country: "CI", national: "" }), "Saisissez votre numéro de téléphone.");
  assert.match(phoneError({ country: "CI", national: "07 00" }) ?? "", /trop court pour Côte d’Ivoire\. Exemple : 07 00 00 00 00/);
  assert.match(phoneError({ country: "FR", national: "06 12 34 56 78 90 12" }) ?? "", /trop long pour France/);
  assert.equal(phoneError({ country: "CI", national: "0700000000" }), null);
});

test("mise en forme pendant la saisie", () => {
  assert.equal(formatNational("0700000000", "CI"), "07 00 00 00 00");
  assert.equal(formatNational("07000000001234", "CI"), "07 00 00 00 00");
  assert.equal(formatNational("0612345678", "FR"), "06 12 34 56 78");
  assert.equal(exampleNational("CI"), "07 00 00 00 00");
  assert.ok(exampleNational("FR").length > 0);
});

test("numéro collé avec son indicatif : le pays suit", () => {
  assert.deepEqual(splitInternational("+33 6 12 34 56 78"), { country: "FR", national: "06 12 34 56 78" });
  assert.equal(splitInternational("00225 07 00 00 00 00")?.country, "CI");
  assert.equal(splitInternational("07 00 00 00 00"), null);
  assert.equal(splitInternational("+3"), null);                     // indicatif incomplet : le champ garde la saisie
  assert.equal(splitInternational("+3361")?.country, "FR");          // reconnu dès que possible
  assert.deepEqual(fromE164("+2250700000000").country, "CI");
  assert.deepEqual(fromE164(null), { country: "CI", national: "" });
});

test("liste des pays : noms français, drapeau, indicatif ; recherche sans accents, par code ou indicatif", () => {
  const all = allCountries();
  assert.ok(all.length > 200);
  const ci = all.find((c) => c.code === "CI");
  assert.deepEqual(ci, { code: "CI", name: "Côte d’Ivoire", dial: "225", flag: flagOf("CI") });
  assert.equal(countryName("US"), "États-Unis");
  assert.equal(searchCountries("cote")[0].code, "CI");
  assert.equal(searchCountries("+225")[0].code, "CI");
  assert.equal(searchCountries("etats")[0].code, "US");
  assert.equal(searchCountries("sn")[0].code, "SN");
  assert.equal(searchCountries("").length, all.length);
});

test("affichage et masquage", () => {
  assert.equal(displayPhone("+2250700000000"), "+225 07 00 00 00 00");
  assert.equal(displayPhone("+33612345678"), "+33 6 12 34 56 78");
  assert.equal(maskPhone("+2250700000002"), "+225 •• •• •• 02");
  assert.equal(maskPhone("+33612345678"), "+33 •• •• •• 78");
});
