from collections import defaultdict
from operator import itemgetter
from typing import Any, Dict, List, Set, Tuple

from qgis.core import NULL, QgsFeature, QgsGeometry, QgsPointXY, QgsSpatialIndex, QgsVectorLayer


class StreamsPointNumerator:
    """Klasa odpowiedzialna za numerowanie punktów na podstawie geometrii cieków i starych numerów."""

    def __init__(self, streams_layer: QgsVectorLayer, points_layer: QgsVectorLayer) -> None:
        """
        Inicjalizacja numeratora punktów.

        Args:
            streams_layer: Warstwa wektorowa zawierająca cieki (geometria liniowa)
            points_layer: Warstwa wektorowa zawierająca punkty (geometria punktowa)

        Raises:
            ValueError: Jeśli warstwy są nieprawidłowe lub brakuje wymaganych pól
        """
        if not streams_layer or not streams_layer.isValid():
            raise ValueError("Warstwa cieków jest nieprawidłowa lub nie istnieje")

        if not points_layer or not points_layer.isValid():
            raise ValueError("Warstwa punktów jest nieprawidłowa lub nie istnieje")

        self.streams_layer: QgsVectorLayer = streams_layer
        self.points_layer: QgsVectorLayer = points_layer
        self.field_old_number: str = "numer-stary"
        self.field_new_number: str = "numer-nowy"
        self.field_stream_mark: str = "oznaczenie"

        # Walidacja wymaganych pól
        self._validate_required_fields()

        self.unified_streams_geometries: Dict[str, QgsGeometry] = {}  # {stream_mark: unified_geometry}
        self.streams_points: Dict[str, List[Dict[str, Any]]] = defaultdict(
            list
        )  # {stream_id: [{"point_id": point_id, ...}, ...]}
        self.stream_old_points: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.point_features: Dict[int, QgsFeature]
        self.point_index: QgsSpatialIndex
        self.point_features, self.point_index = self.spatial_index(self.points_layer)

    def _validate_required_fields(self) -> None:
        """
        Waliduje czy wymagane pola istnieją w warstwach.

        Raises:
            ValueError: Jeśli brakuje wymaganych pól
        """
        # Sprawdź pola w warstwie cieków
        stream_fields = [field.name() for field in self.streams_layer.fields()]
        if self.field_stream_mark not in stream_fields:
            raise ValueError(f"Warstwa cieków nie zawiera pola '{self.field_stream_mark}'")

        # Sprawdź pola w warstwie punktów
        point_fields = [field.name() for field in self.points_layer.fields()]
        if self.field_old_number not in point_fields:
            raise ValueError(f"Warstwa punktów nie zawiera pola '{self.field_old_number}'")
        if self.field_new_number not in point_fields:
            raise ValueError(f"Warstwa punktów nie zawiera pola '{self.field_new_number}'")

    @staticmethod
    def spatial_index(vector_layer: QgsVectorLayer) -> Tuple[Dict[int, QgsFeature], QgsSpatialIndex]:
        """
        Tworzy indeks przestrzenny dla warstwy wektorowej.

        Args:
            vector_layer: Warstwa wektorowa do indeksowania

        Returns:
            Tuple zawierający słownik cech (feature_id -> feature) oraz indeks przestrzenny

        Raises:
            RuntimeError: Jeśli wystąpi błąd podczas tworzenia indeksu
        """
        try:
            allfeatures: Dict[int, QgsFeature] = {}
            index = QgsSpatialIndex()
            for feat in vector_layer.getFeatures():
                feat_copy = QgsFeature(feat)
                allfeatures[feat.id()] = feat_copy
                index.insertFeature(feat_copy)
            print(f"Utworzono indeks przestrzenny dla {len(allfeatures)} obiektów")
            return allfeatures, index
        except Exception as e:
            print(f"✗ Błąd podczas tworzenia indeksu przestrzennego: {e}")
            raise RuntimeError(f"Nie udało się utworzyć indeksu przestrzennego: {e}")

    def union_stream_geometries(self) -> None:
        """
        Łączy geometrie cieków o tym samym oznaczeniu w jeden obiekt.

        Raises:
            RuntimeError: Jeśli wystąpi błąd podczas łączenia geometrii
        """
        try:
            streams_geoms: Dict[str, List[QgsGeometry]] = defaultdict(list)
            stream_start_points: Dict[str, Set[QgsPointXY]] = defaultdict(set)
            stream_end_points: Dict[str, Set[QgsPointXY]] = defaultdict(set)

            for stream in self.streams_layer.getFeatures():
                stream_mark = stream[self.field_stream_mark]
                if stream_mark is None or stream_mark == NULL or stream_mark == "":
                    print(f"⚠ Ciek o ID {stream.id()} nie ma oznaczenia - pomijam")
                    continue

                stream_geom = stream.geometry()
                if stream_geom.isEmpty():
                    print(f"⚠ Ciek '{stream_mark}' (ID {stream.id()}) ma pustą geometrię - pomijam")
                    continue

                if stream_geom.isMultipart():
                    # Warstwa cieków ma typ geometrii MultiLineString, ale w rzeczywistości składa się z pojedynczych linii,
                    # więc konwertujemy do pojedynczego typu geometrii
                    stream_geom.convertToSingleType()

                stream_polyline = stream_geom.asPolyline()
                if len(stream_polyline) < 2:
                    print(f"⚠ Ciek '{stream_mark}' (ID {stream.id()}) ma zbyt mało punktów - pomijam")
                    continue

                # Zbieramy punkty startowe i końcowe dla każdego oznaczenia cieku,
                # aby po złączeniu geometri zweryfikować kierunek cieku
                stream_start_points[stream_mark].add(stream_polyline[0])
                stream_end_points[stream_mark].add(stream_polyline[-1])
                streams_geoms[stream_mark].append(stream_geom)

            # Po zebraniu geometrii dla każdego oznaczenia cieku łączymy je w jeden obiekt
            for stream_mark, stream_geometries in streams_geoms.items():
                if len(stream_geometries) == 1:
                    self.unified_streams_geometries[stream_mark] = stream_geometries[0]
                else:
                    union_geom = QgsGeometry.unaryUnion(stream_geometries)
                    merged_geom = QgsGeometry.mergeLines(union_geom)
                    if merged_geom.isMultipart():
                        merged_geom.convertToSingleType()
                    self.unified_streams_geometries[stream_mark] = merged_geom

            # Weryfikujemy kierunek cieku po złączeniu geometrii - jeśli punkt startowy złączonej geometrii jest dokładnie
            # taki sam jak punkt końcowy oryginalnej geometrii, odwracamy kolejność punktów w złączonej geometrii
            for stream_mark, unified_geom in self.unified_streams_geometries.items():
                unified_polyline = unified_geom.asPolyline()
                unified_start_point = unified_polyline[0]
                if unified_start_point in stream_end_points[stream_mark]:
                    reversed_polyline = list(reversed(unified_polyline))
                    self.unified_streams_geometries[stream_mark] = QgsGeometry.fromPolylineXY(reversed_polyline)

            print(f"Połączono geometrie dla {len(self.unified_streams_geometries)} cieków")

        except Exception as e:
            print(f"✗ Błąd podczas łączenia geometrii cieków: {e}")
            raise RuntimeError(f"Nie udało się połączyć geometrii cieków: {e}")

    def assign_points_to_streams(self) -> None:
        """
        Przypisuje punkty do cieków.

        Raises:
            RuntimeError: Jeśli wystąpi błąd podczas przypisywania punktów
        """
        try:
            # Zbuduj index przestrzenny dla punków, aby szybko znaleźć potencjalne dopasowania
            for stream_mark, unified_geom in self.unified_streams_geometries.items():
                if unified_geom.isEmpty():
                    print(f"⚠ Ciek '{stream_mark}' ma pustą geometrię - pomijam")
                    continue

                # Znajdź punkty w pobliżu złączonej geometrii cieku
                point_candidate_ids = self.point_index.intersects(unified_geom.boundingBox())

                for point_id in point_candidate_ids:
                    point_feat = self.point_features[point_id]
                    point_geom = point_feat.geometry()
                    if point_geom.isEmpty():
                        continue

                    # Sprawdź, czy punkt leży na złączonej geometrii cieku
                    # Dodajemy niewielki bufor, aby uwzględnić niedokładności danych
                    unified_geom_buffered = unified_geom.buffer(0.0000001, 5)
                    if not point_geom.intersects(unified_geom_buffered):
                        continue

                    # Jeśli punkt leży na złączonej geometrii, przypisz go do tego cieku
                    distance = unified_geom.lineLocatePoint(point_geom)
                    point_old_number = point_feat[self.field_old_number]

                    if point_old_number != NULL and point_old_number is not None and point_old_number != "":
                        # Wymaganie 1: Przepisz stary numer do nowego
                        point_new_number = point_old_number
                    else:
                        point_old_number = None
                        point_new_number = None

                    stream_point: Dict[str, Any] = {
                        "point_id": point_id,
                        "distance": distance,
                        "old_number": point_old_number,
                        "new_number": point_new_number,
                    }
                    self.streams_points[stream_mark].append(stream_point)

            # Po przypisaniu punktów do cieków sortujemy listę punktów dla każdego cieku według odległości od początku cieku
            for stream_mark, stream_points in self.streams_points.items():
                stream_points.sort(key=itemgetter("distance"))
                for i, stream_point in enumerate(stream_points):
                    # Dodajemy indeks punktu w kolejności na ciekach, co ułatwi późniejsze numerowanie
                    stream_point["index"] = i
                    # Jeśli punkt ma stary numer, dodajemy go do listy punktów z numerami dla tego cieku
                    if stream_point["old_number"] is not None:
                        self.stream_old_points[stream_mark].append(stream_point)

                print(
                    f"Ciek '{stream_mark}': {len(stream_points)} punktów, z czego {len(self.stream_old_points[stream_mark])} ma stary numer"
                )

        except Exception as e:
            print(f"✗ Błąd podczas przypisywania punktów do cieków: {e}")
            raise RuntimeError(f"Nie udało się przypisać punktów do cieków: {e}")

    def generate_letter_suffix(self, num: int) -> str:
        """
        Generuje sufiks literowy dla danej liczby.

        Args:
            num: Liczba do konwersji (0='a', 1='b', ..., 25='z', 26='aa', ...)

        Returns:
            Sufiks literowy
        """
        if num < 26:
            return chr(ord("a") + num)
        else:
            return self.generate_letter_suffix(num // 26 - 1) + chr(ord("a") + num % 26)

    @staticmethod
    def numerate_points_before_old(stream_points: List[Dict[str, Any]], old_points: List[Dict[str, Any]]) -> None:
        """
        Numeruje punkty PRZED pierwszym punktem ze starym numerem.

        Args:
            stream_points: Lista wszystkich punktów na cieku
            old_points: Lista punktów ze starymi numerami

        Format: 1Pnowy, 2Pnowy, 3Pnowy, ...
        """
        first_old_index = old_points[0]["index"]
        if first_old_index > 0:
            for i in range(first_old_index):
                stream_points[i]["new_number"] = f"{i + 1}Pnowy"

    @staticmethod
    def numerate_points_after_old(stream_points: List[Dict[str, Any]], old_points: List[Dict[str, Any]]) -> None:
        """
        Numeruje punkty PO ostatnim punkcie ze starym numerem.

        Args:
            stream_points: Lista wszystkich punktów na cieku
            old_points: Lista punktów ze starymi numerami

        Format: 6P, 7P, 8P, ... (kontynuacja numeracji)
        """
        last_old_index = old_points[-1]["index"]

        if last_old_index < len(stream_points) - 1:
            # Wyciągnij numer bazowy z ostatniego punktu (np. "5P" -> 5)
            last_base_number = int(old_points[-1]["old_number"][:-1])

            # Numeruj dalej od następnego numeru
            for i in range(last_old_index + 1, len(stream_points)):
                offset = i - last_old_index
                new_number = last_base_number + offset
                stream_points[i]["new_number"] = f"{new_number}P"

    def numerate_points_between_old(
        self, stream_points: List[Dict[str, Any]], old_points: List[Dict[str, Any]]
    ) -> None:
        """
        Numeruje punkty MIĘDZY punktami ze starymi numerami.

        Args:
            stream_points: Lista wszystkich punktów na cieku
            old_points: Lista punktów ze starymi numerami

        Format: 5Pa, 5Pb, 5Pc, ... (gdzie 5 to numer poprzedniego punktu)
        """
        for i in range(len(old_points) - 1):
            current_old_point = old_points[i]
            current_old_index = current_old_point["index"]
            next_old_point = old_points[i + 1]
            next_old_index = next_old_point["index"]

            # Oblicz ile punktów jest między obecnym a następnym punktem ze starym numerem
            points_between_count = next_old_index - current_old_index - 1

            if points_between_count > 0:
                # Wyciągnij numer bazowy z poprzedniego punktu (np. "5P" -> "5")
                base_number = current_old_point["old_number"][:-1]

                # Numeruj punkty dodając kolejne litery alfabetu
                for j in range(points_between_count):
                    letter_suffix = self.generate_letter_suffix(j)
                    point_index = current_old_index + j + 1
                    stream_points[point_index]["new_number"] = f"{base_number}P{letter_suffix}"

    def numerate_points(self) -> None:
        """
        Numeruje punkty zgodnie z wymaganiami zadania.

        Raises:
            RuntimeError: Jeśli wystąpi błąd podczas numerowania punktów
        """
        try:
            for stream_mark, stream_points in self.streams_points.items():
                old_points = self.stream_old_points[stream_mark]

                if not old_points:
                    # Brak punktów ze starymi numerami - numeruj wszystko od 1 do n z sufiksem P
                    for i, point in enumerate(stream_points):
                        point["new_number"] = f"{i + 1}P"
                else:
                    # Numeruj punkty w trzech sekcjach:
                    self.numerate_points_before_old(stream_points, old_points)  # 1. Przed pierwszym
                    self.numerate_points_between_old(stream_points, old_points)  # 2. Między punktami
                    self.numerate_points_after_old(stream_points, old_points)  # 3. Po ostatnim

            print("Numeracja punktów zakończona pomyślnie")
        except Exception as e:
            print(f"✗ Błąd podczas numerowania punktów: {e}")
            raise RuntimeError(f"Nie udało się ponumerować punktów: {e}")

    def update_points_layer(self) -> None:
        """
        Aktualizuje warstwę punktów nowymi numerami.

        Raises:
            RuntimeError: Jeśli wystąpi błąd podczas aktualizacji warstwy
        """
        try:
            # Zbierz wszystkie punkty z przypisanymi nowymi numerami
            points_to_update: Dict[int, str] = {}
            for stream_mark, stream_points in self.streams_points.items():
                for point in stream_points:
                    if point["new_number"] is not None:
                        points_to_update[point["point_id"]] = point["new_number"]

            # Rozpocznij edycję warstwy
            if not self.points_layer.startEditing():
                raise RuntimeError("Nie udało się rozpocząć edycji warstwy punktów")

            # Znajdź indeks pola "numer-nowy"
            field_index = self.points_layer.fields().indexFromName(self.field_new_number)
            if field_index == -1:
                self.points_layer.rollBack()
                raise ValueError(f"Nie znaleziono pola '{self.field_new_number}' w warstwie punktów")

            # Aktualizuj punkty
            for point_id, new_number in points_to_update.items():
                if not self.points_layer.changeAttributeValue(point_id, field_index, new_number):
                    print(f"⚠ Nie udało się zaktualizować punktu o ID {point_id}")

            # Dla punktów, które nie są na ciekach, ustaw NULL
            for point_id in self.point_features.keys():
                if point_id not in points_to_update:
                    self.points_layer.changeAttributeValue(point_id, field_index, NULL)

            # Zatwierdź zmiany
            if not self.points_layer.commitChanges():
                errors = self.points_layer.commitErrors()
                raise RuntimeError(f"Nie udało się zatwierdzić zmian w warstwie punktów: {errors}")

            print(f"Zaktualizowano {len(points_to_update)} punktów")

        except Exception as e:
            # W przypadku błędu cofnij zmiany
            if self.points_layer.isEditable():
                self.points_layer.rollBack()
            print(f"✗ Błąd podczas aktualizacji warstwy punktów: {e}")
            raise RuntimeError(f"Nie udało się zaktualizować warstwy punktów: {e}")

    def run(self) -> None:
        """
        Główna metoda uruchamiająca cały proces numeracji.

        Raises:
            RuntimeError: Jeśli wystąpi błąd podczas procesu numeracji
        """
        try:
            print("Rozpoczęcie procesu numeracji punktów")

            # Krok 1: Połącz geometrie cieków
            print("Krok 1/4: Łączenie geometrii cieków...")
            self.union_stream_geometries()

            # Krok 2: Przypisz punkty do cieków
            print("Krok 2/4: Przypisywanie punktów do cieków...")
            self.assign_points_to_streams()

            # Krok 3: Numeruj punkty
            print("Krok 3/4: Numerowanie punktów...")
            self.numerate_points()

            # Krok 4: Aktualizuj warstwę punktów
            print("Krok 4/4: Aktualizacja warstwy punktów...")
            self.update_points_layer()

            print("Proces numeracji punktów zakończony pomyślnie!")

        except Exception as e:
            print(f"✗ Błąd podczas procesu numeracji: {e}")
            raise RuntimeError(f"Proces numeracji nie powiódł się: {e}")


def main() -> None:
    """
    Funkcja główna uruchamiająca proces numeracji punktów z konsoli QGIS.

    Raises:
        ValueError: Jeśli nie znaleziono wymaganych warstw w projekcie
        RuntimeError: Jeśli wystąpi błąd podczas procesu numeracji
    """
    try:
        from qgis.core import QgsProject

        # Pobierz warstwy z projektu QGIS
        project = QgsProject.instance()

        # Pobierz warstwy
        streams_layers = project.mapLayersByName("cieki")
        if not streams_layers:
            raise ValueError(
                "Nie znaleziono warstwy 'cieki' w projekcie. "
                "Upewnij się, że warstwa jest załadowana i ma odpowiednią nazwę."
            )
        streams_layer = streams_layers[0]

        points_layers = project.mapLayersByName("punkty")
        if not points_layers:
            raise ValueError(
                "Nie znaleziono warstwy 'punkty' w projekcie. "
                "Upewnij się, że warstwa jest załadowana i ma odpowiednią nazwę."
            )
        points_layer = points_layers[0]

        # Utwórz instancję numeratora
        print("Inicjalizacja numeratora punktów...")
        numerator = StreamsPointNumerator(streams_layer, points_layer)

        # Uruchom proces numeracji
        numerator.run()

        print("✓ Numeracja punktów zakończona pomyślnie!")

    except ValueError as e:
        print(f"✗ Błąd walidacji: {e}")
        raise
    except RuntimeError as e:
        print(f"✗ Błąd wykonania: {e}")
        raise
    except Exception as e:
        print(f"✗ Nieoczekiwany błąd: {e}")
        raise RuntimeError(f"Nieoczekiwany błąd podczas numeracji: {e}")


# Uruchom, tylko jeśli skrypt jest wykonywany bezpośrednio z konsoli QGIS
if __name__ == "__console__" or __name__ == "__main__":
    main()
