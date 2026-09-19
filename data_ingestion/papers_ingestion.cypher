CALL apoc.periodic.iterate(
  "CALL apoc.load.json('file:///papers.jsonl') YIELD value AS paper RETURN paper",
  "
    // ----- PAPER -----
    MERGE (p:PaperSource {doi: paper.metadata.doi})
    SET p.title = paper.metadata.title

    UNWIND paper.materials AS mat
    CREATE (m:Material)
    SET m.material_id      = mat.material_id,
        m.name             = mat.name,
        m.original_name    = mat.original_name,
        m.chemical_formula = mat.formula,
        m.role             = mat.role
    MERGE (m)-[:REPORTED_IN]->(p)

    // Morphology
    FOREACH (morph_desc IN CASE WHEN mat.morphology IS NOT NULL AND mat.morphology <> '' THEN [mat.morphology] ELSE [] END |
      MERGE (morph:Morphology {description: morph_desc})
      MERGE (m)-[:HAS_MORPHOLOGY]->(morph)
    )

    // Electrolyte label
    FOREACH (_ IN CASE WHEN mat.electrolyte = true THEN [1] ELSE [] END |
      SET m:Electrolyte
    )

    // ----- SYNTHESIS (always a list) -----
    FOREACH (step IN mat.synthesis_route |
      CREATE (s:SynthesisStep)
      SET s.step_id     = step.step_id,
          s.order       = step.order,
          s.description = step.method
      MERGE (m)-[:PRODUCED_BY]->(s)
      MERGE (s)-[:REPORTED_IN]->(p)
      MERGE (sm:SynthesisMethod {name: step.method})
      MERGE (s)-[:USES_METHOD]->(sm)

      FOREACH (prec IN step.precursors_parsed |
        MERGE (pc:Precursor {name: prec.clean_name})
        ON CREATE SET pc.original_name = prec.original_name,
                      pc.role_hint = prec.role
        MERGE (s)-[:USES_PRECURSOR]->(pc)
        MERGE (pc)-[:REPORTED_IN]->(p)
      )
      FOREACH (param IN step.parameters |
        CREATE (par:Parameter)
        SET par = param
        MERGE (s)-[:HAS_PARAMETER]->(par)
      )
    )

    // ----- PROPERTIES -----
    FOREACH (prop IN mat.performance_and_properties |
      CREATE (pr:Property)
      SET pr.property_id           = prop.property_id,
          pr.property_name         = prop.property_name,
          pr.original_property_name = prop.original_property_name,
          pr.value                 = prop.value,
          pr.unit                  = prop.unit,
          pr.original_value        = prop.original_value,
          pr.original_unit         = prop.original_unit
      MERGE (m)-[:EXHIBITS_PROPERTY]->(pr)
      MERGE (pr)-[:REPORTED_IN]->(p)

      FOREACH (cond IN prop.test_conditions |
        CREATE (tc:TestCondition)
        SET tc.condition_id   = cond.cond_id,
            tc.condition_name = cond.condition_name,
            tc.raw_value      = cond.value
        FOREACH (_ IN CASE WHEN cond.condition_name = 'electrolyte' THEN [1] ELSE [] END |
          MERGE (e:Electrolyte:Material {name: cond.electrolyte_original})
          ON CREATE SET e.material_id = randomUUID(),
                        e.role = 'electrolyte',
                        e.components_json = cond.electrolyte_components_json,
                        e.solvent = cond.electrolyte_solvent
          ON MATCH SET e.components_json = cond.electrolyte_components_json,
                       e.solvent = cond.electrolyte_solvent
          MERGE (pr)-[:USING_ELECTROLYTE]->(e)
          MERGE (e)-[:REPORTED_IN]->(p)
        )
        FOREACH (_ IN CASE WHEN cond.condition_name <> 'electrolyte' THEN [1] ELSE [] END |
          SET tc.value = cond.numeric_value,
              tc.unit  = cond.parsed_unit
        )
        MERGE (pr)-[:MEASURED_UNDER]->(tc)
      )
    )
  ",
  {batchSize: 50, iterateList: true}
)