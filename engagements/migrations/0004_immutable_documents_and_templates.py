"""Immuabilité garantie PAR LA BASE (déclencheurs PostgreSQL) et modèles de contrat livrés « À valider juridiquement ».

 - Documents scellés : aucune suppression ; aucune modification sauf la révocation, une seule fois.
 - Signatures des parties et historique des contrats : ajout seulement (ni modification, ni suppression).
   (TRUNCATE, utilisé seulement pour vider une base de test, n'est pas concerné.)
 - Deux modèles (emploi domestique salarié, prestation indépendante) au statut « À valider juridiquement » : aucun n'est utilisable
   avant la validation humaine d'un juriste (personnel « contracts.legal_review »)."""
from django.db import migrations

TRIGGERS = """
CREATE OR REPLACE FUNCTION eng_document_immutable() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Document de contrat immuable : suppression interdite (%)', OLD.reference;
  END IF;
  IF (NEW.contract_id, NEW.kind, NEW.stage, NEW.reference, NEW.version, NEW.parent_id, NEW.amendment_id, NEW.file, NEW.sha256, NEW.size,
      NEW.terms_hash, NEW.token_hash, NEW.signing_key_kid, NEW.signature, NEW.issued_at, NEW.issued_by_id)
     IS DISTINCT FROM
     (OLD.contract_id, OLD.kind, OLD.stage, OLD.reference, OLD.version, OLD.parent_id, OLD.amendment_id, OLD.file, OLD.sha256, OLD.size,
      OLD.terms_hash, OLD.token_hash, OLD.signing_key_kid, OLD.signature, OLD.issued_at, OLD.issued_by_id) THEN
    RAISE EXCEPTION 'Document de contrat immuable : seule la révocation est permise (%)', OLD.reference;
  END IF;
  IF OLD.revoked_at IS NOT NULL AND (NEW.revoked_at, NEW.revoked_reason, NEW.revoked_by_id)
                                    IS DISTINCT FROM (OLD.revoked_at, OLD.revoked_reason, OLD.revoked_by_id) THEN
    RAISE EXCEPTION 'Révocation définitive : elle ne peut être ni modifiée ni annulée (%)', OLD.reference;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION eng_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Table en ajout seulement (%) : % interdit', TG_TABLE_NAME, TG_OP;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS eng_document_immutable ON engagements_contractdocument;
CREATE TRIGGER eng_document_immutable BEFORE UPDATE OR DELETE ON engagements_contractdocument
  FOR EACH ROW EXECUTE FUNCTION eng_document_immutable();
DROP TRIGGER IF EXISTS eng_signature_append_only ON engagements_contractsignature;
CREATE TRIGGER eng_signature_append_only BEFORE UPDATE OR DELETE ON engagements_contractsignature
  FOR EACH ROW EXECUTE FUNCTION eng_append_only();
DROP TRIGGER IF EXISTS eng_event_append_only ON engagements_contractevent;
CREATE TRIGGER eng_event_append_only BEFORE UPDATE OR DELETE ON engagements_contractevent
  FOR EACH ROW EXECUTE FUNCTION eng_append_only();
"""

DROP = """
DROP TRIGGER IF EXISTS eng_document_immutable ON engagements_contractdocument;
DROP TRIGGER IF EXISTS eng_signature_append_only ON engagements_contractsignature;
DROP TRIGGER IF EXISTS eng_event_append_only ON engagements_contractevent;
DROP FUNCTION IF EXISTS eng_document_immutable();
DROP FUNCTION IF EXISTS eng_append_only();
"""


def seed_templates(apps, schema_editor):
    from engagements.legal import SEED_TEMPLATES

    Template = apps.get_model("engagements", "ContractTemplate")
    for seed in SEED_TEMPLATES:
        Template.objects.get_or_create(code=seed["code"], version=1, defaults={
            "title": seed["title"], "relationship": seed["relationship"], "articles": seed["articles"](),
            "legal_references": seed["references"], "status": "to_review",
            "review_note": "Modèle livré par Tratra : À VALIDER JURIDIQUEMENT. Références et emplacements « [À compléter par la revue "
                           "juridique] » à vérifier et compléter par un juriste avant toute validation."})


class Migration(migrations.Migration):

    dependencies = [
        ('engagements', '0003_contract_modes'),
    ]

    operations = [
        migrations.RunSQL(TRIGGERS, DROP),
        migrations.RunPython(seed_templates, migrations.RunPython.noop),
    ]
