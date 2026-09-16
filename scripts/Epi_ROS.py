"""
=============================================================================
Atención de Brote de Rabia de Origen Silvestre
Instructivo PRA-SPA-I-041 V.2 - ICA
Modelo de círculos concéntricos (Piccini)
=============================================================================
Genera tres capas alrededor de un caso confirmado:
    - Zona_Focal       (buffer configurable, por defecto 1 km)
    - Zona_Perifoco    (buffer configurable, por defecto 5 km)
    - Anillo_Perifoco  (diferencia entre perifoco y foco)

Las capas se crean en memoria y se añaden automáticamente al proyecto.
No se exponen parámetros de salida en el diálogo del algoritmo.
=============================================================================
"""

from typing import Any, Optional

from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProcessingMultiStepFeedback,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterNumber,
    QgsProcessingParameterCrs,
    QgsProcessingUtils,
    QgsMemoryProviderUtils,
    QgsProject,
)
from qgis import processing


class AtencionBroteRabiaSilvestre(QgsProcessingAlgorithm):

    # ── Entradas ──
    INPUT_FOCO = 'foco_ros'
    INPUT_CRS = 'crs_analisis'
    INPUT_DIST_FOCO = 'distancia_foco'
    INPUT_DIST_PERIFOCO = 'distancia_perifoco'

    # ── Claves internas de resultados ──
    OUT_FOCO = 'Zona_Focal'
    OUT_PERIFOCO = 'Zona_Perifoco'
    OUT_ANILLO = 'Anillo_Perifoco'

    # ─────────────────────────────────────────────────────────────
    def initAlgorithm(self, config: Optional[dict[str, Any]] = None):

        # ══════════ ENTRADAS ══════════

        self.addParameter(QgsProcessingParameterVectorLayer(
            self.INPUT_FOCO, 'Punto focal (caso confirmado)',
            types=[QgsProcessing.TypeVectorPoint], defaultValue=None))

        self.addParameter(QgsProcessingParameterCrs(
            self.INPUT_CRS, 'CRS proyectado para análisis (UTM de la zona)',
            defaultValue='EPSG:32618'))

        self.addParameter(QgsProcessingParameterNumber(
            self.INPUT_DIST_FOCO, 'Radio del foco (metros)',
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=1000, minValue=100))

        self.addParameter(QgsProcessingParameterNumber(
            self.INPUT_DIST_PERIFOCO, 'Radio del perifoco (metros)',
            type=QgsProcessingParameterNumber.Integer,
            defaultValue=5000, minValue=500))

    # ─────────────────────────────────────────────────────────────
    def _materializar(self, temp_path, context, nombre, crs):
        """Convierte una capa temporal en capa en memoria y la añade al proyecto."""
        src = QgsProcessingUtils.mapLayerFromString(temp_path, context)
        if src is None:
            return None

        lyr = QgsMemoryProviderUtils.createMemoryLayer(
            nombre,
            src.fields(),
            src.wkbType(),
            crs
        )
        if lyr is None:
            return None

        dp = lyr.dataProvider()
        feats = list(src.getFeatures())
        if feats:
            dp.addFeatures(feats)
            lyr.updateExtents()

        QgsProject.instance().addMapLayer(lyr)
        return lyr.id()

    # ─────────────────────────────────────────────────────────────
    def processAlgorithm(
        self,
        parameters: dict[str, Any],
        context: QgsProcessingContext,
        model_feedback: QgsProcessingFeedback
    ) -> dict[str, Any]:

        feedback = QgsProcessingMultiStepFeedback(4, model_feedback)
        results = {}
        outputs = {}

        crs_analisis = self.parameterAsCrs(parameters, self.INPUT_CRS, context)

        # ── PASO 1: Reproyectar punto focal ──
        feedback.pushInfo('Paso 1/4: Reproyectando punto focal al CRS métrico...')
        outputs['punto_reproyectado'] = processing.run(
            'native:reprojectlayer',
            {'INPUT': parameters[self.INPUT_FOCO],
             'TARGET_CRS': crs_analisis,
             'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT},
            context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(1)
        if feedback.isCanceled():
            return {}
        punto_metrico = outputs['punto_reproyectado']['OUTPUT']

        # ── PASO 2: Buffer FOCO ──
        feedback.pushInfo('Paso 2/4: Generando buffer de la zona focal...')
        outputs['zona_focal'] = processing.run(
            'native:buffer',
            {'INPUT': punto_metrico,
             'DISTANCE': parameters[self.INPUT_DIST_FOCO],
             'DISSOLVE': True,
             'END_CAP_STYLE': 0, 'JOIN_STYLE': 0, 'MITER_LIMIT': 2,
             'SEGMENTS': 36, 'SEPARATE_DISJOINT': False,
             'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT},
            context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(2)
        if feedback.isCanceled():
            return {}

        # ── PASO 3: Buffer PERIFOCO ──
        feedback.pushInfo('Paso 3/4: Generando buffer de la zona perifoco...')
        outputs['zona_perifoco'] = processing.run(
            'native:buffer',
            {'INPUT': punto_metrico,
             'DISTANCE': parameters[self.INPUT_DIST_PERIFOCO],
             'DISSOLVE': True,
             'END_CAP_STYLE': 0, 'JOIN_STYLE': 0, 'MITER_LIMIT': 2,
             'SEGMENTS': 36, 'SEPARATE_DISJOINT': False,
             'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT},
            context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(3)
        if feedback.isCanceled():
            return {}

        # ── PASO 4: Anillo de perifoco ──
        feedback.pushInfo('Paso 4/4: Calculando anillo de perifoco...')
        outputs['anillo_perifoco'] = processing.run(
            'native:difference',
            {'INPUT': outputs['zona_perifoco']['OUTPUT'],
             'OVERLAY': outputs['zona_focal']['OUTPUT'],
             'OUTPUT': QgsProcessing.TEMPORARY_OUTPUT},
            context=context, feedback=feedback, is_child_algorithm=True)

        feedback.setCurrentStep(4)
        if feedback.isCanceled():
            return {}

        # ── MATERIALIZAR CAPAS Y AÑADIRLAS AL PROYECTO ──
        feedback.pushInfo('Añadiendo capas al proyecto...')

        lid = self._materializar(
            outputs['zona_focal']['OUTPUT'], context,
            'Zona_Focal', crs_analisis)
        if lid:
            results[self.OUT_FOCO] = lid
            feedback.pushInfo(f'✓ Zona Focal añadida (id={lid})')

        lid = self._materializar(
            outputs['zona_perifoco']['OUTPUT'], context,
            'Zona_Perifoco', crs_analisis)
        if lid:
            results[self.OUT_PERIFOCO] = lid
            feedback.pushInfo(f'✓ Zona Perifoco añadida (id={lid})')

        lid = self._materializar(
            outputs['anillo_perifoco']['OUTPUT'], context,
            'Anillo_Perifoco', crs_analisis)
        if lid:
            results[self.OUT_ANILLO] = lid
            feedback.pushInfo(f'✓ Anillo Perifoco añadido (id={lid})')

        feedback.pushInfo('✓ Procesamiento completado.')
        return results

    # ─────────────────────────────────────────────────────────────
    def name(self) -> str:
        return 'atencion_brote_rabia_silvestre'

    def displayName(self) -> str:
        return 'Atención de brote de rabia de origen silvestre'

    def group(self) -> str:
        return 'Sanidad Animal - Rabia'

    def groupId(self) -> str:
        return 'sanidad_animal_rabia'

    def createInstance(self):
        return AtencionBroteRabiaSilvestre()
